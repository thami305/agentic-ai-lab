"""Pattern C — explicit graph with deterministic routing (lab-03-style).

Nodes: validate -> extract -> assess -> review -> publish, with a
conflict -> human_review branch. Reuses lab03.graph.Graph with
proposal-specific state and nodes.

- validate: deterministic input check.
- extract: model-driven (seeded policy) retrieval + finding construction.
- assess: deterministic citation validation + conflict detection.
  Conflicting findings (same passage, different severity) or citation
  violations route to human_review.
- review: deterministic Review assembly (dedupe, severity sort,
  verdict_for with seeded jitter) + post-validation.
- publish / human_review / clarify: terminals.

The graph path is recorded on the state; tests assert on it directly.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from lab03.graph import Graph, Node

from .common import PatternResult, finalize
from .issues import ISSUES, Issue
from .loop import ToolResult
from .proposal import Proposal, load_proposal
from .schemas import Evidence, Finding, Review
from .seeded import _BROAD_QUERY
from .tools import build_registry
from .validate import unsupported_claims, validate_review, verdict_for

Terminal = Literal["clarify", "human_review", "publish"]


@dataclass
class ReviewState:
    question: str
    proposal: Proposal
    seed: int
    passages: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    review: Review | None = None
    validation_violations: list[str] = field(default_factory=list)
    conflict_detail: str | None = None
    retrieval_log: list[tuple[str, str]] = field(default_factory=list)
    trace: list[ToolResult] = field(default_factory=list)
    tool_calls_made: int = 0
    total_tokens: int = 0
    verdict_jitter: bool = False
    inject_conflict: bool = False  # test hook: plant a conflicting finding
    terminal: Terminal | None = None
    terminal_reason: str | None = None
    path: list[str] = field(default_factory=list)

    def note(self, node: str) -> None:
        self.path.append(node)


# ------------------------------------------------------------- nodes ---

def validate_input(state: ReviewState) -> None:
    if not state.question.strip():
        state.terminal_reason = (
            "clarification: the review request is empty — nothing to review.")


def extract(state: ReviewState) -> None:
    """Seeded retrieval policy: search, fetch top-n passages, build findings
    for fetched issues (seeded include/drop). Every tool call is logged so
    the measurement harness sees the same trace shape as the agent loops."""
    rng = random.Random(state.seed)
    include = {i.id: rng.random() < 0.75 for i in ISSUES}
    n_fetch = rng.randint(5, 8)
    state.verdict_jitter = rng.random() < 0.35

    reg = build_registry(state.proposal)
    hits = reg.get("search_proposal").fn(query=_BROAD_QUERY, limit=8)
    state.tool_calls_made += 1
    get = reg.get("get_passage").fn
    fetched_ids: list[str] = []
    for h in hits[:n_fetch]:
        pid = h["passage_id"]
        passage = get(passage_id=pid)
        state.tool_calls_made += 1
        state.retrieval_log.append(("get_passage", pid))
        state.trace.append(ToolResult(name="get_passage",
                                      arguments={"passage_id": pid},
                                      ok=True, data=passage))
        state.passages.append(passage)
        fetched_ids.append(pid)

    findings = [Finding(claim=i.claim, severity=i.severity,  # type: ignore[arg-type]
                        evidence=Evidence(passage_id=i.passage_id, quote=i.quote))
                for i in ISSUES
                if i.passage_id in fetched_ids and include[i.id]]
    if not findings and fetched_ids:
        first = next(i for i in ISSUES if i.passage_id in fetched_ids)
        findings = [Finding(claim=first.claim, severity=first.severity,  # type: ignore[arg-type]
                            evidence=Evidence(passage_id=first.passage_id,
                                              quote=first.quote))]
    if state.inject_conflict and findings:
        dup = findings[0]
        other_severity = ("low" if dup.severity == "high" else "high")
        findings.append(Finding(claim=dup.claim + " (conflicting read)",
                                severity=other_severity,  # type: ignore[arg-type]
                                evidence=dup.evidence))
    state.findings = findings
    state.total_tokens += rng.randint(700, 1300) + rng.randint(120, 320)


def detect_conflict(findings: list[Finding]) -> str | None:
    """Two findings conflict when they make the SAME claim about the same
    passage but assign it different severities — a genuine disagreement the
    graph cannot reconcile without a human. Two *different* findings that
    happen to cite the same passage (e.g. the SLA passage supports both a
    best-efforts finding and a discretionary-credits finding) are not a
    conflict."""
    for i in range(len(findings)):
        for j in range(i + 1, len(findings)):
            a, b = findings[i], findings[j]
            same_claim = (a.claim == b.claim
                          or a.claim.startswith(b.claim)
                          or b.claim.startswith(a.claim))
            if (a.evidence.passage_id == b.evidence.passage_id
                    and a.severity != b.severity and same_claim):
                return (f"conflicting findings on passage "
                        f"'{a.evidence.passage_id}': severities "
                        f"{sorted({a.severity, b.severity})} for the same claim")
    return None


def assess(state: ReviewState) -> None:
    violations: list[str] = []
    for i, f in enumerate(state.findings):
        passage = state.proposal.by_id(f.evidence.passage_id)
        if passage is None:
            violations.append(f"finding[{i}]: unknown passage_id")
        elif f.evidence.quote not in passage.text:
            # passage text is whitespace-normalized on load; catalog quotes
            # are single-spaced, so this matches validate.py's check
            violations.append(f"finding[{i}]: quote not verbatim")
    state.validation_violations = violations
    state.conflict_detail = detect_conflict(state.findings)


def review(state: ReviewState) -> None:
    order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted(state.findings,
                      key=lambda f: (order[f.severity], f.evidence.passage_id))
    seen: set[tuple[str, str]] = set()
    deduped = [f for f in findings
               if not ((f.evidence.passage_id, f.claim) in seen
                       or seen.add((f.evidence.passage_id, f.claim)))]
    base = verdict_for(deduped)
    verdict = base
    if any(f.severity == "high" for f in deduped) and state.verdict_jitter:
        verdict = "revise" if base == "reject" else "reject"
    risks: list[str] = []
    for issue in ISSUES:
        if any(f.evidence.passage_id == issue.passage_id
               and f.claim.startswith(issue.claim[:40]) for f in deduped):
            if issue.risk not in risks:
                risks.append(issue.risk)
    state.review = Review(verdict=verdict, findings=deduped, risks=risks)  # type: ignore[arg-type]
    report = validate_review(state.review, state.proposal)
    state.validation_violations = report.violations


def publish(state: ReviewState) -> None:
    assert state.review is not None
    state.terminal_reason = (
        f"published: review with {len(state.review.findings)} findings, "
        f"verdict '{state.review.verdict}'.")


def human_review(state: ReviewState) -> None:
    if state.terminal_reason is None:
        detail = state.conflict_detail or "; ".join(state.validation_violations)
        state.terminal_reason = f"human review: {detail}"


def clarify(state: ReviewState) -> None:
    if state.terminal_reason is None:
        state.terminal_reason = (
            "clarification: no proposal passages were retrieved — nothing "
            "to review.")


# ----------------------------------------------------------- routers ---

def route_after_validate(state: ReviewState) -> str:
    return "clarify" if not state.question.strip() else "extract"


def route_after_assess(state: ReviewState) -> str:
    if state.conflict_detail or state.validation_violations:
        return "human_review"
    if not state.findings:
        return "clarify"
    return "review"


def route_after_review(state: ReviewState) -> str:
    return "human_review" if state.validation_violations else "publish"


# ------------------------------------------------------------ graph ---

def build_review_graph() -> Graph:
    g = Graph(entry="validate")
    g.add(Node("validate", "deterministic", validate_input,
               router=route_after_validate))
    g.add(Node("extract", "model", extract, router=lambda s: "assess"))
    g.add(Node("assess", "deterministic", assess, router=route_after_assess))
    g.add(Node("review", "deterministic", review, router=route_after_review))
    g.add(Node("publish", "deterministic", publish, terminal="publish"))
    g.add(Node("human_review", "deterministic", human_review,
               terminal="human_review"))
    g.add(Node("clarify", "deterministic", clarify, terminal="clarify"))
    return g


QUESTION = ("Review this vendor proposal and produce a structured review: "
            "verdict (accept/revise/reject), findings with severity and "
            "verbatim evidence, and risks.")


def run_pattern_c(seed: int, proposal: Proposal | None = None,
                  inject_conflict: bool = False) -> PatternResult:
    proposal = proposal or load_proposal()
    started = time.monotonic()
    state = ReviewState(question=QUESTION, proposal=proposal, seed=seed,
                        inject_conflict=inject_conflict)
    graph = build_review_graph()
    graph.run(state)
    latency = time.monotonic() - started
    error = None
    if state.terminal != "publish":
        error = f"not_published: terminal={state.terminal} ({state.terminal_reason})"
        review = None
    else:
        review = state.review
    return finalize("C", seed, review, state.trace, state.tool_calls_made,
                    state.total_tokens, latency, proposal, error=error,
                    extra={"path": list(state.path),
                           "terminal": state.terminal})
