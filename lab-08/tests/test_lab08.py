"""Lab 8 acceptance tests: one task, three orchestration patterns.

Conventions: all tests deterministic — stub backends, no network, no API
key. Stochasticity enters only through SeededStub(random.Random(seed)),
and the seeded tests assert per-seed determinism explicitly.
"""
from __future__ import annotations

import pytest
from lab02.models import ScriptedStub, calls, final_raw, tc
from pydantic import ValidationError

from lab08.common import tool_accuracy
from lab08.evaluate import (PATTERN_NAMES, aggregate, decide_winner,
                            key_figures, measure)
from lab08.issues import ISSUES
from lab08.loop import AgentLoop, LoopConfig, ToolResult
from lab08.pattern_a import run_pattern_a, run_pattern_a_oracle
from lab08.pattern_b import (Handoff, merge_reviews, route_domain,
                             run_pattern_b, run_pattern_b_oracle,
                             run_specialist)
from lab08.pattern_c import build_review_graph, run_pattern_c
from lab08.proposal import load_proposal
from lab08.schemas import Evidence, Finding, Review
from lab08.seeded import DomainSeededStub, SeededStub
from lab08.tools import (build_pricing_registry, build_registry,
                         build_terms_registry)
from lab08.validate import (unsupported_claims, validate_review,
                            verdict_for)

from conftest import review_payload_for


# ------------------------------------------------------- proposal/data ---

def test_proposal_loads(proposal):
    pids = [p.pid for p in proposal.passages]
    assert pids == [f"PROP-P{i}" for i in range(1, 10)]
    sections = {p.section for p in proposal.passages}
    assert {"Pricing", "Terms", "Delivery/SLA"} <= sections
    wc = proposal.word_count()
    assert 600 <= wc <= 900, f"proposal is {wc} words, want 600-900"


def test_issue_quotes_are_verbatim(proposal):
    """Every catalog quote must be a verbatim substring of its passage —
    the stubs can only be citation-honest if the catalog is."""
    for issue in ISSUES:
        passage = proposal.by_id(issue.passage_id)
        assert passage is not None, issue.id
        assert issue.quote in passage.text, (
            f"{issue.id}: quote not verbatim in {issue.passage_id}")


def test_verdict_for_rules():
    def f(sev: str) -> Finding:
        return Finding(claim="a claim about the proposal text here",
                       severity=sev,  # type: ignore[arg-type]
                       evidence=Evidence(passage_id="PROP-P1", quote="x"))
    assert verdict_for([f("high")] * 3) == "reject"
    assert verdict_for([f("high")]) == "revise"
    assert verdict_for([f("medium")]) == "revise"
    assert verdict_for([f("low")]) == "accept"
    assert verdict_for([f("high"), f("medium")]) == "revise"


def test_validate_review_catches_fabrication(proposal):
    payload = review_payload_for("F-PAY-1")
    payload["findings"][0]["evidence"]["quote"] = (
        "the vendor promises free ponies forever")
    review = Review(**payload)
    report = validate_review(review, proposal)
    assert not report.ok
    assert any("verbatim" in v for v in report.violations)
    assert unsupported_claims(review, proposal) == 1


def test_validate_review_rejects_accept_with_highs(proposal):
    payload = review_payload_for("F-ESC-1")
    payload["verdict"] = "accept"
    report = validate_review(Review(**payload), proposal)
    assert not report.ok
    assert any("accept" in v for v in report.violations)


# ------------------------------------------------------------ pattern A ---

def test_pattern_a_oracle_correct(proposal):
    res = run_pattern_a_oracle(proposal)
    assert res.error is None, res.error
    assert res.success, "oracle review must be schema-valid and fully cited"
    assert res.verdict_sane
    assert res.review.verdict in ("revise", "reject")
    assert res.unsupported == 0
    assert len(res.review.findings) >= 5
    assert {f.severity for f in res.review.findings} >= {"high", "medium"}


def test_pattern_a_loop_rejects_unknown_tool(proposal):
    payload = review_payload_for("F-PAY-1", "F-ETF-1")
    script = [calls(tc("bogus_tool", {})),
              calls(tc("search_proposal", {"query": "fees", "limit": 5})),
              final_raw(payload)]
    loop = AgentLoop(ScriptedStub(script), build_registry(proposal))
    res = loop.run("review the proposal", Review,
                   validator=lambda r: validate_review(r, proposal))
    assert res.status == "completed", res.error
    assert res.tool_trace[0].error.startswith("unknown_tool")
    assert res.tool_calls_made == 2  # the bogus call executed nothing


def test_pattern_a_budget_enforced(proposal):
    script = [calls(tc("search_proposal", {"query": "x", "limit": 5}))] * 6
    loop = AgentLoop(ScriptedStub(script), build_registry(proposal),
                     LoopConfig(max_turns=8, max_tool_calls=2))
    res = loop.run("review the proposal", Review)
    assert res.status == "error"
    assert "budget_exceeded" in res.error


# ------------------------------------------------------------ pattern B ---

def test_pattern_b_oracle_correct(proposal):
    res = run_pattern_b_oracle(proposal)
    assert res.error is None, res.error
    assert res.success
    assert res.verdict_sane
    assert res.review.verdict == "reject"  # 3 high-severity findings
    pricing_pids = {p.pid for p in proposal.in_sections("Pricing")}
    terms_pids = {p.pid for p in proposal.in_sections("Terms", "Delivery/SLA")}
    cited = {f.evidence.passage_id for f in res.review.findings}
    assert cited & pricing_pids, "pricing specialist findings missing"
    assert cited & terms_pids, "terms specialist findings missing"
    assert res.unsupported == 0


def test_pattern_b_tool_isolation(proposal):
    """The pricing specialist cannot call the terms specialist's tools:
    the allow-list rejects the call and it is recorded, never executed."""
    payload = review_payload_for("F-PAY-1")
    script = [calls(tc("get_terms_passage", {"passage_id": "PROP-P4"})),
              final_raw(payload)]
    handoff = Handoff(from_agent="manager", to_agent="pricing_specialist",
                      task="Review the proposal pricing.",
                      context={"domain": "pricing"})
    spec = run_specialist("pricing_specialist", handoff, proposal,
                          backend=ScriptedStub(script))
    assert spec.error is None, spec.error
    assert any(t.error and t.error.startswith("unknown_tool")
               for t in spec.trace), "cross-domain call must be rejected"
    pricing_pids = {p.pid for p in proposal.in_sections("Pricing")}
    for f in spec.review.findings:
        assert f.evidence.passage_id in pricing_pids


def test_pattern_b_handoffs_typed_and_routed(proposal):
    assert route_domain("Review the pricing, fees and payment terms.") == "pricing"
    assert route_domain("Review the SLA, liability and renewal terms.") == "terms"
    res = run_pattern_b(0, proposal)
    assert res.error is None, res.error
    handoffs = res.extra["handoffs"]
    assert len(handoffs) == 4
    for h in handoffs:
        assert isinstance(h, Handoff)
        assert h.from_agent and h.to_agent and h.task
        assert isinstance(h.context, dict)
    outs = [h for h in handoffs if h.from_agent == "manager"]
    assert {h.to_agent for h in outs} == {"pricing_specialist",
                                          "terms_specialist"}
    backs = [h for h in handoffs if h.to_agent == "manager"]
    assert all("review" in h.context for h in backs)


def test_pattern_b_seeded_determinism(proposal):
    r1, r2 = run_pattern_b(3, proposal), run_pattern_b(3, proposal)
    assert r1.review.model_dump() == r2.review.model_dump()
    assert r1.tokens == r2.tokens and r1.tool_calls == r2.tool_calls


def test_merge_reviews_deterministic(proposal):
    payload = review_payload_for("F-ESC-1", "F-PAY-1")
    merged = merge_reviews([Review(**payload), Review(**payload)])
    assert len(merged.findings) == 2  # deduped
    assert [f.severity for f in merged.findings] == ["high", "low"]
    assert merged.verdict == "revise"


# ------------------------------------------------------------ pattern C ---

def test_pattern_c_happy_path(proposal):
    res = run_pattern_c(0, proposal)
    assert res.error is None, res.error
    assert res.success
    assert res.verdict_sane
    assert res.extra["terminal"] == "publish"
    assert res.extra["path"] == ["validate", "extract", "assess",
                                 "review", "publish"]
    assert res.review.verdict in ("revise", "reject")
    assert res.unsupported == 0


def test_pattern_c_conflict_branch(proposal):
    """Injected conflicting findings (same passage, different severity)
    must route to the human review branch, never to publish."""
    res = run_pattern_c(0, proposal, inject_conflict=True)
    assert res.extra["terminal"] == "human_review"
    assert "human_review" in res.extra["path"]
    assert "publish" not in res.extra["path"]
    assert res.review is None  # conflicting review never ships


def test_detect_conflict_only_flags_same_claim():
    from lab08.pattern_c import detect_conflict

    def f(claim: str, sev: str, pid: str = "PROP-P7") -> Finding:
        return Finding(claim=claim, severity=sev,  # type: ignore[arg-type]
                       evidence=Evidence(passage_id=pid, quote="x"))
    # Two DIFFERENT findings citing the same passage: not a conflict.
    assert detect_conflict([f("best efforts sla is vague", "high"),
                            f("credits are discretionary", "medium")]) is None
    # The SAME claim with different severities: a conflict.
    assert detect_conflict([f("best efforts sla is vague", "high"),
                            f("best efforts sla is vague", "low")]) is not None


def test_pattern_c_clarify_on_empty_question(proposal):
    state_cls = build_review_graph()
    from lab08.pattern_c import ReviewState
    state = ReviewState(question="   ", proposal=proposal, seed=0)
    state_cls.run(state)
    assert state.terminal == "clarify"
    assert state.path[0] == "validate"


# ------------------------------------------------- measurement harness ---

def test_seeded_determinism_per_seed(proposal):
    """Same seed -> identical run; different seeds -> measurable variance."""
    r1, r2 = run_pattern_a(2, proposal=proposal), run_pattern_a(2, proposal=proposal)
    assert r1.review.model_dump() == r2.review.model_dump()
    assert r1.tokens == r2.tokens
    assert r1.tool_calls == r2.tool_calls
    assert r1.extra["trace_names"] == r2.extra["trace_names"]

    runs = [run_pattern_a(s, proposal=proposal) for s in range(5)]
    signatures = {(tuple((f.claim, f.severity) for f in r.review.findings),
                   r.review.verdict, r.tokens) for r in runs}
    assert len(signatures) > 1, "seeded runs must vary across seeds"


def test_tool_accuracy_definition():
    trace = [
        ToolResult(name="get_passage", arguments={"passage_id": "PROP-P1"},
                   ok=True, data={}),
        ToolResult(name="get_passage", arguments={"passage_id": "PROP-P2"},
                   ok=True, data={}),
        ToolResult(name="get_passage", arguments={"passage_id": "PROP-P9"},
                   ok=True, data={}),  # fetched but never cited
        ToolResult(name="get_passage", arguments={"passage_id": "PROP-X"},
                   ok=False, error="tool_error"),  # failed: excluded
        ToolResult(name="search_proposal", arguments={"query": "x"},
                   ok=True, data=[]),  # not a get_passage call: excluded
    ]
    review = Review(**review_payload_for("F-ESC-1", "F-PAY-1"))
    assert tool_accuracy(trace, review) == pytest.approx(2 / 3)
    assert tool_accuracy([], review) == 1.0  # vacuous: nothing mis-cited
    assert tool_accuracy(trace, None) == 0.0


def test_measurement_harness_reports_variance(proposal):
    results = measure("A", seeds=(0, 1))
    assert len(results) == 2
    agg = aggregate(results)
    for key in ("success_rate", "tool_acc_mean", "tool_acc_std",
                "unsupported_mean", "calls_mean", "calls_std",
                "tokens_mean", "tokens_std", "latency_mean", "latency_std"):
        assert key in agg
    assert all(v >= 0 for v in (agg["tool_acc_std"], agg["tokens_std"],
                                agg["latency_std"]))


# ------------------------------------------------------------- ADR/docs ---

def test_adr_generated_and_consistent():
    """The ADR is generated from measurements: recompute the aggregates in
    the test and check the winner plus every key figure appear verbatim."""
    from lab08.evaluate import LAB_ROOT
    path = LAB_ROOT / "docs" / "adr.md"
    assert path.exists(), "docs/adr.md must be generated by evaluate.py"
    text = path.read_text()
    aggs = {p: aggregate(measure(p)) for p in ("A", "B", "C")}
    winner = decide_winner(aggs)
    assert PATTERN_NAMES[winner] in text
    for fig in key_figures(aggs):
        assert fig in text, f"ADR missing figure: {fig}"


def test_readme_done_checklist():
    from lab08.evaluate import LAB_ROOT
    text = (LAB_ROOT / "README.md").read_text()
    assert "What done means" in text
    for item in ("pytest", "docs/adr.md", "Seeds 0..4",
                 "no network", "no API key"):
        assert item in text, f"README checklist missing: {item}"
