"""Pattern B — manager + two specialists.

The manager routes pricing questions to the PricingSpecialist and terms
questions to the TermsSpecialist; each specialist runs the shared agent loop
against a RESTRICTED tool registry (pricing tools see Pricing passages
only, terms tools see Terms + Delivery/SLA only). Handoffs are explicit
typed messages (Handoff). The manager merges the specialists' findings
deterministically — dedupe, severity sort, verdict_for() — and ships the
merged Review.

The specialists can never call each other's tools: the loop's allow-list
rejects unknown names, and the restricted registries don't even register
the other domain's tools (a test asserts the unknown_tool rejection shows
up in the trace).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from lab02.models import ModelBackend

from .common import PatternResult, finalize
from .issues import Issue, issues_for
from .loop import AgentLoop, LoopConfig, ToolResult
from .proposal import Proposal, load_proposal
from .schemas import Evidence, Finding, Review
from .seeded import DomainSeededStub
from .tools import build_pricing_registry, build_terms_registry
from .validate import validate_review, verdict_for


@dataclass
class Handoff:
    """Explicit typed message between manager and specialists."""
    from_agent: str
    to_agent: str
    task: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpecialistResult:
    agent: str
    review: Review | None
    trace: list[ToolResult]
    tool_calls: int
    tokens: int
    error: str | None


def route_domain(task: str) -> str:
    """Deterministic manager routing: pricing questions go to the pricing
    specialist, everything else (terms, SLA, delivery) to the terms
    specialist."""
    text = task.lower()
    if any(w in text for w in ("pric", "fee", "cost", "payment", "overage",
                               "escalat")):
        return "pricing"
    return "terms"


def _issue_to_finding(issue: Issue) -> Finding:
    return Finding(claim=issue.claim, severity=issue.severity,  # type: ignore[arg-type]
                   evidence=Evidence(passage_id=issue.passage_id,
                                     quote=issue.quote))


def merge_reviews(reviews: list[Review]) -> Review:
    """Deterministic merge: dedupe by (passage_id, claim), order high >
    medium > low then by passage id, verdict from verdict_for()."""
    seen: set[tuple[str, str]] = set()
    findings: list[Finding] = []
    risks: list[str] = []
    for r in reviews:
        for f in r.findings:
            key = (f.evidence.passage_id, f.claim)
            if key not in seen:
                seen.add(key)
                findings.append(f)
        for risk in r.risks:
            if risk not in risks:
                risks.append(risk)
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f.severity], f.evidence.passage_id))
    verdict = verdict_for(findings)
    return Review(verdict=verdict, findings=findings, risks=risks)  # type: ignore[arg-type]


def run_specialist(agent: str, handoff: Handoff,
                   proposal: Proposal,
                   backend: ModelBackend | None = None,
                   config: LoopConfig | None = None) -> SpecialistResult:
    domain = handoff.context.get("domain", route_domain(handoff.task))
    if backend is None:
        # Deterministic fallback seed (no hash(): str hashing is
        # process-randomized). Callers pass an explicit backend anyway.
        backend = DomainSeededStub(
            domain, seed=(len(agent) * 131 + len(handoff.task)) & 0xFFFF)
    registry = (build_pricing_registry(proposal) if domain == "pricing"
                else build_terms_registry(proposal))
    loop = AgentLoop(backend, registry, config or LoopConfig())
    res = loop.run(handoff.task, Review,
                   validator=lambda r: validate_review(r, proposal))
    review = res.final if isinstance(res.final, Review) else None
    return SpecialistResult(agent=agent, review=review,
                            trace=res.tool_trace,
                            tool_calls=res.tool_calls_made,
                            tokens=res.total_tokens,
                            error=None if res.status == "completed" else res.error)


def run_pattern_b(seed: int, proposal: Proposal | None = None,
                  config: LoopConfig | None = None) -> PatternResult:
    """Manager run: two routed handoffs, deterministic merge. Per-seed
    determinism comes from derived specialist seeds (seed*2+1, seed*2+2)."""
    proposal = proposal or load_proposal()
    started = time.monotonic()
    handoffs: list[Handoff] = []
    specialist_results: list[SpecialistResult] = []

    for i, (agent, domain) in enumerate(
            (("pricing_specialist", "pricing"), ("terms_specialist", "terms"))):
        task = ("Review the proposal's "
                + ("pricing, fees, and payment terms." if domain == "pricing"
                   else "contract terms, liability, renewal, and SLA."))
        out = Handoff(from_agent="manager", to_agent=agent, task=task,
                      context={"domain": domain})
        handoffs.append(out)
        assert route_domain(task) == domain  # routing is deterministic
        spec = run_specialist(
            agent, out, proposal,
            backend=DomainSeededStub(domain, seed * 2 + 1 + i),
            config=config)
        specialist_results.append(spec)
        handoffs.append(Handoff(from_agent=agent, to_agent="manager",
                                task="Findings for merge.",
                                context={"domain": domain,
                                         "review": (spec.review.model_dump()
                                                    if spec.review else None),
                                         "error": spec.error}))

    reviews = [s.review for s in specialist_results if s.review is not None]
    errors = [s.error for s in specialist_results if s.error]
    merged = merge_reviews(reviews) if reviews else None
    if merged is not None and errors:
        merged = None  # a failed specialist poisons the merge: no ship
    latency = time.monotonic() - started

    trace: list[ToolResult] = []
    for s in specialist_results:
        trace.extend(s.trace)
    tokens = sum(s.tokens for s in specialist_results)
    calls = sum(s.tool_calls for s in specialist_results)
    error = None if merged is not None else (
        "merge_failed: " + "; ".join(errors or ["no specialist reviews"]))

    return finalize("B", seed, merged, trace, calls, tokens, latency,
                    proposal, error=error,
                    extra={"handoffs": handoffs,
                           "specialists": [s.agent for s in specialist_results]})


def run_pattern_b_oracle(proposal: Proposal | None = None) -> PatternResult:
    """Deterministic oracle run for the correctness tests (no randomness)."""
    from lab02.models import ScriptedStub, calls, final_raw, tc
    proposal = proposal or load_proposal()
    payloads = {}
    for domain in ("pricing", "terms"):
        issues = issues_for(domain)
        payloads[domain] = {
            "verdict": verdict_for([_issue_to_finding(i) for i in issues]),
            "findings": [{"claim": i.claim, "severity": i.severity,
                          "evidence": {"passage_id": i.passage_id,
                                       "quote": i.quote}} for i in issues],
            "risks": [i.risk for i in issues]}
    started = time.monotonic()
    trace: list[ToolResult] = []
    tokens = 0
    calls_made = 0
    reviews: list[Review] = []
    for domain in ("pricing", "terms"):
        search = "search_pricing" if domain == "pricing" else "search_terms"
        script = [calls(tc(search, {"query": "fees", "limit": 5})),
                  final_raw(payloads[domain])]
        loop = AgentLoop(ScriptedStub(script),
                         build_pricing_registry(proposal) if domain == "pricing"
                         else build_terms_registry(proposal))
        res = loop.run(f"oracle {domain}", Review,
                       validator=lambda r: validate_review(r, proposal))
        assert res.status == "completed", res.error
        reviews.append(res.final)  # type: ignore[arg-type]
        trace.extend(res.tool_trace)
        tokens += res.total_tokens
        calls_made += res.tool_calls_made
    merged = merge_reviews(reviews)
    latency = time.monotonic() - started
    return finalize("B", 0, merged, trace, calls_made, tokens, latency,
                    proposal)
