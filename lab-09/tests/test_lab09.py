"""Lab 9 acceptance tests — deterministic, no network, no API key.

Covers: golden-file validity (50 versioned cases, unique ids, all six
categories), tracer spans per run, deterministic scoring (green pass case,
red bad-citation case, red unexpected-tool-call case), stub-grader
calibration, gate green on healthy code, gate RED with the citation
validator disabled (the centerpiece regression test), and thresholds loaded
from file rather than hardcoded.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from lab02 import agent as agent_mod
from lab02.models import PromptOnlyStub
from lab02.packet import load_packet
from lab02.schemas import ResearchBrief
from lab02.validate import ValidationReport, validate_brief
from lab09.gate import load_thresholds, run_gate
from lab09.grader import load_calibration
from lab09.runner import CaseResult, load_golden, run_case, score_case
from lab09.tracer import Tracer

REQUIRED_CATEGORIES = {"happy_paths", "ambiguous", "missing_data",
                       "tool_errors", "adversarial",
                       "previously_observed_failures"}


# ------------------------------------------------- golden file validity ---

def test_golden_file_has_50_cases(golden):
    assert len(golden) == 50


def test_golden_ids_unique_and_versioned(golden):
    ids = [c["id"] for c in golden]
    assert len(set(ids)) == 50, "duplicate case ids"
    for c in golden:
        assert c["version"] == "v1", c["id"]
        assert c["target"] in ("agent", "graph"), c["id"]
        assert isinstance(c["input"]["question"], str), c["id"]
        exp = c["expectations"]
        assert "terminal" in exp and "allowed_tools" in exp, c["id"]


def test_golden_covers_all_categories(golden):
    cats = {c["category"] for c in golden}
    assert REQUIRED_CATEGORIES <= cats, f"missing: {REQUIRED_CATEGORIES - cats}"


def test_golden_inputs_are_small(golden):
    for c in golden:
        assert len(c["input"]["question"]) <= 500, c["id"]


# ------------------------------------------------------------- tracer ---

def test_tracer_records_model_and_tool_spans(by_id):
    result = run_case(by_id["h01"])  # agent + oracle
    spans = result.trace["spans"]
    model_spans = [s for s in spans if s["span"] == "model"]
    tool_spans = [s for s in spans if s["span"] == "tool"]
    assert len(model_spans) >= 2, "oracle takes >= 2 model turns"
    assert {s["name"] for s in tool_spans} == {"search_docs", "get_passage"}
    for s in spans:
        assert set(s) == {"span", "name", "latency_ms", "tokens",
                          "ok", "detail"}, s
        assert s["latency_ms"] >= 0


def test_tracer_captures_graph_path(by_id):
    result = run_case(by_id["h11"])  # graph happy path
    assert result.path == ["validate_input", "retrieve", "assess",
                           "synthesize", "validate", "publish"]
    assert result.trace["path"] == result.path
    path_spans = [s["name"] for s in result.trace["spans"]
                  if s["span"] == "path"]
    assert path_spans == result.path


def test_tracer_records_error_and_retry_spans(by_id):
    failed = run_case(by_id["t01"])  # tool fn raises
    err_spans = [s for s in failed.trace["spans"] if s["span"] == "error"]
    assert err_spans and err_spans[0]["name"] == "flaky_search"
    assert not any(s["ok"] for s in failed.trace["spans"]
                   if s["span"] == "tool" and s["name"] == "flaky_search")

    retried = run_case(by_id["t09"])  # graph flaky:99 -> stop
    retry_spans = [s for s in retried.trace["spans"]
                   if s["span"] == "retry"]
    assert len(retry_spans) == 3  # 3 attempts, all fail


# ------------------------------------------------- deterministic scoring ---

def test_scoring_pass_case_green(by_id):
    result = run_case(by_id["h01"])
    scored = score_case(by_id["h01"], result)
    assert scored["pass"], scored["checks"]
    assert scored["unsupported_claims"] == 0


def test_scoring_bad_citation_case_red():
    """A brief with fabricated quotes fails the citation check even when the
    run 'succeeds' — this is what the validator-disabled regression relies
    on."""
    stub = PromptOnlyStub()
    stub.start_run("", "How utilized is Northwind's current warehouse?", [])
    brief = stub.next().final  # ResearchBrief with fabricated quotes
    assert isinstance(brief, ResearchBrief)
    packet = load_packet()
    assert not validate_brief(brief, packet).ok  # deterministically caught
    result = CaseResult(
        case_id="synthetic", target="agent", terminal="publish",
        brief=brief.model_dump(),
        tool_names=[], claims=brief.model_dump()["claims"],
        reasoning_text="", brief_text=json.dumps(brief.model_dump()),
        trace={"case_id": "synthetic", "spans": [], "path": []},
        unsupported_claims=3)
    case = {"id": "synthetic", "version": "v1", "category": "adversarial",
            "target": "agent", "input": {"question": "q", "backend": "x"},
            "expectations": {"terminal": "publish", "allowed_tools": [],
                             "min_claims": 2}}
    scored = score_case(case, result)
    assert not scored["pass"]
    assert not scored["checks"]["citations"]["pass"]
    assert scored["unsupported_claims"] == 3


def test_scoring_unexpected_tool_call_red(by_id):
    result = run_case(by_id["h01"])
    case = dict(by_id["h01"])
    case["expectations"] = {**case["expectations"],
                            "allowed_tools": ["search_docs"]}  # drops get_passage
    scored = score_case(case, result)
    assert not scored["pass"]
    assert not scored["checks"]["tools"]["pass"]
    assert "get_passage" in scored["checks"]["tools"]["detail"]


def test_scoring_injection_stays_out_of_reasoning(by_id):
    result = run_case(by_id["x01"])
    scored = score_case(by_id["x01"], result)
    assert scored["pass"], scored["checks"]
    # quoting the payload as *evidence* is allowed; adopting it as reasoning
    # is not — reasoning must stay clean.
    assert "Ignore all previous instructions" not in result.reasoning_text


# ------------------------------------------------- grader calibration ---

def test_stub_grader_agrees_with_deterministic_checks(calibration,
                                                      thresholds_path):
    from lab09.grader import StubGrader

    def det_verdict(case, res):
        return "pass" if score_case(case, res)["pass"] else "fail"

    grader = StubGrader()
    report = grader.agreement(calibration, det_verdict)
    # the labeled verdicts must also match reality (labels are honest)
    for e in calibration:
        res = CaseResult(**e["result"])
        assert det_verdict(e["case"], res) == e["label"], e["id"]
    thresholds = load_thresholds(thresholds_path)
    assert report["rate"] >= thresholds["min_agreement"], report
    assert report["rate"] == 1.0, report["mismatches"]


# ------------------------------------------------- gate: green and red ---

def test_gate_green_on_healthy_code(thresholds_path):
    report = run_gate(thresholds_path=thresholds_path)
    assert report["green"], report
    assert report["verdict"] == "GREEN"
    assert report["cases_passed"] == report["cases_total"] == 50
    assert report["checks"]["pass_rate"]["value"] == 1.0
    assert report["checks"]["max_unsupported_claims"]["value"] == 0


def test_gate_red_with_validator_disabled(monkeypatch, thresholds_path):
    """Centerpiece regression test: disable lab02's citation post-validator
    (the 'deterministic code decides' half) and the gate must go RED.
    monkeypatch restores the validator afterwards."""
    monkeypatch.setattr(
        agent_mod, "validate_brief",
        lambda brief, packet: ValidationReport(ok=True, violations=[]))
    report = run_gate(thresholds_path=thresholds_path)
    assert not report["green"], "gate stayed green with validator disabled"
    assert report["verdict"] == "RED"
    assert not report["checks"]["pass_rate"]["pass"]
    assert not report["checks"]["max_unsupported_claims"]["pass"]
    # fabricated-quote cases now ship invalid briefs instead of erroring
    assert any("f02" in f for f in report["failing_cases"])


def test_validator_restored_after_regression_test(thresholds_path):
    # Runs after the monkeypatched test: proves the patch was reverted and
    # the gate is green again on the real validator.
    report = run_gate(thresholds_path=thresholds_path)
    assert report["green"]


def test_thresholds_loaded_from_file_not_hardcoded(tmp_path,
                                                   thresholds_path):
    # A stricter thresholds file must change the gate outcome: thresholds
    # come from the file, not from code.
    strict = {"min_pass_rate": 1.0, "max_unsupported_claims": 0,
              "min_agreement": 1.01}  # impossible agreement bar
    strict_path = tmp_path / "thresholds.json"
    strict_path.write_text(json.dumps(strict))
    report = run_gate(thresholds_path=strict_path)
    assert not report["green"]
    assert not report["checks"]["grader_agreement"]["pass"]
    assert report["checks"]["grader_agreement"]["threshold"] == 1.01
    # and the shipped file really drives the default run
    assert load_thresholds(thresholds_path) == {
        "min_pass_rate": 1.0, "max_unsupported_claims": 0,
        "min_agreement": 0.9}


# ------------------------------------------------- trace emission ---

def test_run_golden_cli_writes_one_trace_per_case(tmp_path, monkeypatch):
    from lab09 import run_golden

    outdir = tmp_path / "traces"
    golden = (Path(__file__).resolve().parent.parent
              / "data" / "golden.jsonl")
    monkeypatch.setattr(
        "sys.argv",
        ["run_golden", "--golden", str(golden), "--out", str(outdir)])
    assert run_golden.main() == 0
    written = sorted(outdir.glob("*.json"))
    assert len(written) == 50
    sample = json.loads(written[0].read_text())
    assert set(sample) == {"case_id", "spans", "path"}
    assert sample["spans"], "every trace records at least one span"
