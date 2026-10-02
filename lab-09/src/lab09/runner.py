"""Lab 9 golden-set runner: execute cases, score them deterministically.

A case: {id, version, category, target, input, expectations, label?}
  target: "agent" | "graph"
  input:  {question, backend?, policy?, config?, registry?}

Backends (agent target) are named builders — no live model, no network:
  oracle, prompt_only, scripted_decline, scripted_budget, scripted_max_turns,
  scripted_model_error, scripted_bad_brief, scripted_unknown_tool,
  scripted_invalid_args, scripted_tool_error, scripted_tool_error_recover,
  scripted_bad_source, scripted_altered_quote

Policies (graph target): oracle, flaky:<n>, bad_brief

Registries: "default" (lab02 build_registry) or "flaky_tool" (adds a tool
whose fn raises — for tool-error cases).

Deterministic checks per case (this is the "deterministic code decides"
half of the teaching model):
  1. schema: a shipped brief/decline parses (agent/graph enforce this).
  2. citations: every shipped brief passes the REAL lab02 validate_brief.
  3. terminal: the run's terminal matches expectations.terminal.
  4. tools: every tool name executed ⊆ expectations.allowed_tools.
  5. min_claims / forbidden_text / forbidden_in_reasoning when specified.

Terminal mapping: agent "completed"->"publish", "declined"->"declined",
"error"->"error"; graph uses state.terminal directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lab02.agent import Agent, AgentConfig
from lab02.models import (OracleStub, PromptOnlyStub, ScriptedStub, calls,
                          decline, final_brief, final_raw, tc)
from lab02.packet import all_passages, load_packet
from lab02.schemas import Claim, Evidence
from lab02.tools import ToolDef, ToolRegistry, build_registry, keywords, score_passage
from lab02.validate import validate_brief as _real_validate_brief
from lab02.schemas import SearchDocsArgs
from lab03.nodes import build_graph
from lab03.policies import BadBriefPolicy, FlakyPolicy, OraclePolicy
from lab03.state import BriefState

from .tracer import (Tracer, TracedBackend, instrument_graph,
                     instrument_policy, traced_tool_registry)

LAB03_PACKET = (Path(__file__).resolve().parent.parent.parent.parent
                / "lab-03" / "data" / "packet.json")


# ------------------------------------------------------------- cases ---

def load_golden(path: str | Path) -> list[dict[str, Any]]:
    cases = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            case["_lineno"] = lineno
            cases.append(case)
    return cases


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def good_brief_kwargs(question: str, packet: Any) -> dict[str, Any]:
    """A schema-valid, citation-valid brief for an answerable question —
    same construction as the lab02 OracleStub (verbatim first sentences)."""
    keys = keywords(question)
    scored = [(score_passage(keys, p.text), s, p)
              for s, p in all_passages(packet)]
    scored = [(sc, s, p) for sc, s, p in scored if sc > 0]
    scored.sort(key=lambda t: (-t[0], t[1].id, t[2].pid))
    top = scored[:2]
    claims = [Claim(text=_first_sentence(p.text),
                    evidence=[Evidence(source_id=s.id, passage_id=p.pid,
                                       quote=_first_sentence(p.text))])
              for _, s, p in top]
    return {"question": question, "claims": claims, "assumptions": [],
            "open_questions": [],
            "sources_used": sorted({s.id for _, s, _ in top})}


# ------------------------------------------------- backend builders ---

def _flaky_search_fn(**kwargs: Any) -> Any:
    raise RuntimeError("simulated tool outage")


def build_registry_for_case(packet: Any, name: str,
                            tracer: Tracer) -> ToolRegistry:
    reg = build_registry(packet)
    if name == "flaky_tool":
        reg.register(ToolDef(
            name="flaky_search",
            description="Simulated failing search tool.",
            args_model=SearchDocsArgs,
            fn=_flaky_search_fn))
    elif name != "default":
        raise ValueError(f"unknown registry '{name}'")
    return traced_tool_registry(reg, tracer)


def build_backend(name: str, question: str, packet: Any) -> Any:
    if name == "oracle":
        return OracleStub()
    if name == "prompt_only":
        return PromptOnlyStub()
    if name == "scripted_decline":
        return ScriptedStub([decline("The packet contains no documents "
                                     "addressing this question.")])
    if name == "scripted_budget":
        return ScriptedStub(
            [calls(tc("search_docs", {"query": "warehouse", "limit": 5}))] * 6)
    if name == "scripted_max_turns":
        return ScriptedStub(
            [calls(tc("search_docs", {"query": "x", "limit": 5}))] * 10)
    if name == "scripted_model_error":
        return ScriptedStub([])
    if name == "scripted_bad_brief":
        return ScriptedStub([final_raw({"question": question})])
    if name == "scripted_unknown_tool":
        return ScriptedStub([
            calls(tc("delete_docs", {"query": "x"})),
            final_brief(**good_brief_kwargs(question, packet)),
        ])
    if name == "scripted_invalid_args":
        return ScriptedStub([
            calls(tc("search_docs", {"query": "x", "limit": 500})),
            final_brief(**good_brief_kwargs(question, packet)),
        ])
    if name == "scripted_tool_error":
        return ScriptedStub([
            calls(tc("flaky_search", {"query": "warehouse", "limit": 5})),
            decline("Search is unavailable and the packet cannot be "
                    "consulted without it."),
        ])
    if name == "scripted_tool_error_recover":
        return ScriptedStub([
            calls(tc("flaky_search", {"query": "warehouse", "limit": 5})),
            calls(tc("search_docs", {"query": "warehouse", "limit": 5})),
            final_brief(**good_brief_kwargs(question, packet)),
        ])
    if name == "scripted_bad_source":
        kw = good_brief_kwargs(question, packet)
        kw["claims"][0].evidence[0].source_id = "DOC-NOPE"
        return ScriptedStub([final_brief(**kw)])
    if name == "scripted_bad_passage":
        kw = good_brief_kwargs(question, packet)
        kw["claims"][0].evidence[0].passage_id = "DOC-OPS-9"
        return ScriptedStub([final_brief(**kw)])
    if name == "scripted_altered_quote":
        kw = good_brief_kwargs(question, packet)
        q = kw["claims"][0].evidence[0].quote
        kw["claims"][0].evidence[0].quote = q.replace("92%", "99%") \
            if "92%" in q else q + " (altered)"
        return ScriptedStub([final_brief(**kw)])
    raise ValueError(f"unknown backend '{name}'")


def build_policy(name: str) -> Any:
    if name == "oracle":
        return OraclePolicy()
    if name.startswith("flaky:"):
        return FlakyPolicy(fail_times=int(name.split(":")[1]))
    if name == "bad_brief":
        return BadBriefPolicy()
    raise ValueError(f"unknown policy '{name}'")


# ------------------------------------------------------------- results ---

@dataclass
class CaseResult:
    case_id: str
    target: str
    terminal: str
    brief: dict[str, Any] | None = None
    decline_reason: str | None = None
    error: str | None = None
    tool_names: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    reasoning_text: str = ""
    brief_text: str = ""
    tokens: int = 0
    latency_s: float = 0.0
    path: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    unsupported_claims: int = 0


def _unsupported_claims(terminal: str, brief_dict: dict[str, Any] | None,
                        packet: Any) -> int:
    """Per-claim citation failures against the REAL validator — counted only
    for SHIPPED briefs (terminal == "publish"). A bad brief routed to
    "review" was correctly rejected, not shipped: the system worked, so it
    contributes 0. This is the 'max_unsupported_claims' gate metric: what
    would have reached the user."""
    if terminal != "publish" or not brief_dict:
        return 0
    from lab02.schemas import ResearchBrief
    bad = 0
    for claim in brief_dict.get("claims", []):
        mini = ResearchBrief(
            question=brief_dict["question"], claims=[claim],
            assumptions=[], open_questions=[],
            sources_used=brief_dict.get("sources_used", []))
        if not _real_validate_brief(mini, packet).ok:
            bad += 1
    return bad


def run_case(case: dict[str, Any]) -> CaseResult:
    target = case["target"]
    question = case["input"]["question"]
    tracer = Tracer()
    if target == "agent":
        return _run_agent_case(case, question, tracer)
    if target == "graph":
        return _run_graph_case(case, question, tracer)
    raise ValueError(f"unknown target '{target}'")


def _run_agent_case(case: dict[str, Any], question: str,
                    tracer: Tracer) -> CaseResult:
    packet = load_packet()
    backend = TracedBackend(
        build_backend(case["input"].get("backend", "oracle"), question, packet),
        tracer)
    registry = build_registry_for_case(
        packet, case["input"].get("registry", "default"), tracer)
    cfg_kwargs = case["input"].get("config", {}) or {}
    config = AgentConfig(**cfg_kwargs) if cfg_kwargs else AgentConfig()
    agent = Agent(backend, registry, packet, config=config)
    result = agent.run(question)

    terminal = {"completed": "publish", "declined": "declined",
                "error": "error"}[result.status]
    brief = result.brief.model_dump() if result.brief else None
    tool_names = [t.name for t in result.tool_trace]
    tracer.set_path(["agent_run"] + tool_names + [terminal])
    return CaseResult(
        case_id=case["id"], target="agent", terminal=terminal,
        brief=brief,
        decline_reason=result.decline.reason if result.decline else None,
        error=result.error,
        tool_names=tool_names,
        claims=brief["claims"] if brief else [],
        reasoning_text=" ".join((brief.get("assumptions", [])
                                  + brief.get("open_questions", []))
                                 if brief else []),
        brief_text=json.dumps(brief) if brief else "",
        tokens=result.total_tokens, latency_s=result.latency_s,
        path=tracer.path, trace=tracer.to_dict(case["id"]),
        unsupported_claims=_unsupported_claims(terminal, brief, packet))


def _run_graph_case(case: dict[str, Any], question: str,
                    tracer: Tracer) -> CaseResult:
    packet = load_packet(LAB03_PACKET)
    policy = instrument_policy(
        build_policy(case["input"].get("policy", "oracle")), tracer)
    graph = instrument_graph(build_graph(policy), tracer)
    state = graph.run(BriefState(question=question, packet=packet))

    brief = state.brief.model_dump() if state.brief else None
    tool_names = sorted({s["name"] for s in tracer.spans_of("tool")})
    tracer.set_path(list(state.path))
    terminal = state.terminal or "none"
    return CaseResult(
        case_id=case["id"], target="graph", terminal=terminal,
        brief=brief, error=None,
        tool_names=tool_names,
        claims=brief["claims"] if brief else [],
        reasoning_text=" ".join((brief.get("assumptions", [])
                                  + brief.get("open_questions", []))
                                 if brief else []),
        brief_text=json.dumps(brief) if brief else "",
        tokens=state.total_tokens, latency_s=0.0,
        path=list(state.path), trace=tracer.to_dict(case["id"]),
        unsupported_claims=_unsupported_claims(terminal, brief, packet))


# ------------------------------------------------------------- scoring ---

def score_case(case: dict[str, Any], result: CaseResult) -> dict[str, Any]:
    """Deterministic checks. Returns {"checks": {name: {"pass": bool,
    "detail": str}}, "pass": bool, "unsupported_claims": int}."""
    exp = case.get("expectations", {}) or {}
    checks: dict[str, dict[str, Any]] = {}

    def add(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"pass": bool(ok), "detail": detail}

    # 1. expected terminal reached
    add("terminal", result.terminal == exp.get("terminal"),
        f"got '{result.terminal}', expected '{exp.get('terminal')}'")

    # 2. schema: a shipped brief must exist exactly when terminal is publish.
    # review/clarify/stop may carry an internal (possibly invalid) brief —
    # it was rejected, not shipped.
    if result.terminal == "publish":
        add("schema", result.brief is not None,
            "publish requires a brief" if result.brief is None
            else "brief present")
    elif result.terminal == "declined":
        add("schema", result.decline_reason is not None
            and result.brief is None,
            "declined requires a decline reason and no brief")
    elif result.terminal == "error":
        add("schema", result.brief is None,
            "error terminals must not ship a brief")
    else:  # review / clarify / stop: brief is an internal artifact
        add("schema", True, "non-shipping terminal — brief optional")

    # 3. citations validate — only for SHIPPED briefs. A bad brief routed
    # to review was correctly rejected; the system worked.
    if result.terminal == "publish" and result.brief is not None:
        ok = result.unsupported_claims == 0
        add("citations", ok,
            f"{result.unsupported_claims} unsupported claim(s)" if not ok
            else "all citations valid")
    else:
        add("citations", True, "n/a — no brief shipped")

    # 4. no unexpected tool calls
    allowed = set(exp.get("allowed_tools", []))
    unexpected = [n for n in result.tool_names if n not in allowed]
    add("tools", not unexpected,
        f"unexpected tool calls: {unexpected}" if unexpected
        else f"all tool calls allowed: {sorted(set(result.tool_names))}")

    # 5. minimum grounded claims
    if "min_claims" in exp:
        add("min_claims", len(result.claims) >= exp["min_claims"],
            f"{len(result.claims)} claims, need >= {exp['min_claims']}")
    else:
        add("min_claims", True, "n/a — not specified")

    # 6. forbidden text anywhere in the brief
    forbid = exp.get("forbidden_text", []) or []
    hits = [f for f in forbid if f in result.brief_text]
    add("forbidden_text", not hits,
        f"forbidden text present: {hits}" if hits else "clean")

    # 7. forbidden text in the model's own reasoning (assumptions +
    #    open_questions). Mirrors lab-02's injection semantics: quoting an
    #    injection payload as *evidence* is allowed; adopting it as reasoning
    #    is not.
    forbid_r = exp.get("forbidden_in_reasoning", []) or []
    hits_r = [f for f in forbid_r if f in result.reasoning_text]
    add("forbidden_in_reasoning", not hits_r,
        f"payload leaked into reasoning: {hits_r}" if hits_r else "clean")

    return {"checks": checks,
            "pass": all(c["pass"] for c in checks.values()),
            "unsupported_claims": result.unsupported_claims}
