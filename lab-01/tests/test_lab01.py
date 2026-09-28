"""Lab 1 acceptance tests — 20 fixed cases, run unattended.

The plan's PASS WHEN: 20 fixed cases run unattended; no unauthorized tool
executes; all outputs validate; failures return a safe, useful error; token
and latency totals are captured.

The ScriptedStub stands in for the model so every case is deterministic.
The loop, registry, validation, timeouts, retries, caching, and injection
handling are all real and under test.
"""
import time

import pytest

from lab01.agent import Agent, AgentConfig
from lab01.db import INJECTION, seed
from lab01.models import (ScriptedStub, calls, decline, final_raw, final_rec,
                          tc)
from lab01.schemas import EmptyArgs
from lab01.tools import ToolDef, build_registry


@pytest.fixture
def db_path(tmp_path):
    return seed(tmp_path / "pipeline.db")


def make_agent(db_path, script, extra_tools=None, **cfg):
    registry = build_registry(db_path, extra=extra_tools)
    return Agent(ScriptedStub(script), registry, AgentConfig(**cfg))


def hold_rec(client_id, metric_name, metric_value, sources):
    return final_rec(
        client_id=client_id, metric_name=metric_name, metric_value=metric_value,
        recommendation="hold",
        rationale=f"{metric_name} is {metric_value:,.0f}; inside the hold band per the rubric.",
        confidence="high", data_sources=sources)


# ------------------------------------------------------- happy paths ---

def test_01_weighted_pipeline_acme(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "weighted_pipeline", "client_id": "acme"})),
        hold_rec("acme", "weighted_pipeline", 256000.0, ["calculate_metric"]),
    ])
    r = agent.run("What is Acme's weighted pipeline?")
    assert r.status == "completed"
    assert r.recommendation.metric_value == 256000.0
    assert r.recommendation.recommendation == "hold"


def test_02_win_rate_overall(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "win_rate"})),
        hold_rec("all", "win_rate", 0.5, ["calculate_metric"]),
    ])
    r = agent.run("What is our overall win rate?")
    assert r.status == "completed"
    assert r.recommendation.metric_value == pytest.approx(0.5)


def test_03_avg_deal_size_globex(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "avg_deal_size", "client_id": "globex"})),
        hold_rec("globex", "avg_deal_size", 190000.0, ["calculate_metric"]),
    ])
    r = agent.run("Average open deal size for Globex?")
    assert r.status == "completed"
    assert r.recommendation.metric_value == pytest.approx(190000.0)


def test_04_total_pipeline_all_clients(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "total_pipeline"})),
        hold_rec("all", "total_pipeline", 614000.0, ["calculate_metric"]),
    ])
    r = agent.run("Total open pipeline across all clients?")
    assert r.status == "completed"
    assert r.recommendation.metric_value == pytest.approx(614000.0)


def test_05_multi_step_client_then_metric(db_path):
    agent = make_agent(db_path, [
        calls(tc("get_client", {"client_id": "acme"})),
        calls(tc("calculate_metric", {"metric": "weighted_pipeline", "client_id": "acme"})),
        hold_rec("acme", "weighted_pipeline", 256000.0,
                 ["get_client", "calculate_metric"]),
    ])
    r = agent.run("Tell me about Acme and its weighted pipeline.")
    assert r.status == "completed"
    assert r.turns == 3
    assert [t.name for t in r.tool_trace] == ["get_client", "calculate_metric"]
    assert r.tool_trace[0].data["client"]["name"] == "Acme Manufacturing"


def test_06_stage_filter_then_metric(db_path):
    agent = make_agent(db_path, [
        calls(tc("list_deals", {"stage": "negotiation"})),
        calls(tc("calculate_metric", {"metric": "total_pipeline", "stage": "negotiation"})),
        hold_rec("all", "total_pipeline", 500000.0, ["list_deals", "calculate_metric"]),
    ])
    r = agent.run("How much is sitting in negotiation?")
    assert r.status == "completed"
    assert r.tool_trace[0].data["count"] == 2
    assert r.recommendation.metric_value == pytest.approx(500000.0)


# ---------------------------------------------------------- break it ---

def test_07_malformed_arguments_rejected_before_execution(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "bogus"})),
        decline("The requested metric is not supported, so I cannot compute it."),
    ])
    r = agent.run("Compute the bogus metric for Acme.")
    assert r.status == "declined"
    t = r.tool_trace[0]
    assert not t.ok and t.attempts == 0  # never executed
    assert "invalid_arguments" in t.error


def test_08_unknown_tool_never_executes(db_path):
    agent = make_agent(db_path, [
        calls(tc("drop_database", {})),
        hold_rec("acme", "weighted_pipeline", 256000.0, ["calculate_metric"]),
    ])
    r = agent.run("What is Acme's weighted pipeline?")
    t = r.tool_trace[0]
    assert not t.ok and t.attempts == 0  # rejected by the allow-list
    assert "unknown_tool" in t.error
    assert r.status == "completed"  # the run still recovers via a valid final


def test_09_unknown_client_id_is_a_safe_domain_error(db_path):
    agent = make_agent(db_path, [
        calls(tc("get_client", {"client_id": "nope"})),
        final_rec(client_id="nope", metric_name="weighted_pipeline", metric_value=0.0,
                  recommendation="review",
                  rationale="Client id 'nope' does not exist, so no metric could be computed.",
                  confidence="low", data_sources=["get_client"]),
    ])
    r = agent.run("What is Nope Corp's weighted pipeline?")
    assert r.status == "completed"
    assert r.tool_trace[0].ok  # the tool ran fine; the *domain* reports not-found
    assert r.tool_trace[0].data["error"] == "unknown_client"
    assert r.recommendation.confidence == "low"


def test_10_empty_result_is_graceful(db_path):
    agent = make_agent(db_path, [
        calls(tc("list_deals", {"client_id": "acme", "stage": "prospect"})),
        final_rec(client_id="acme", metric_name="total_pipeline", metric_value=0.0,
                  recommendation="review",
                  rationale="Acme has no prospect-stage deals, so there is nothing to evaluate.",
                  confidence="medium", data_sources=["list_deals"]),
    ])
    r = agent.run("Show me Acme's prospect-stage deals.")
    assert r.status == "completed"
    assert r.tool_trace[0].data["count"] == 0


def test_11_tool_timeout_retries_then_safe_error(db_path):
    def slow_probe() -> dict:
        time.sleep(5)
        return {"ok": True}

    slow = ToolDef(name="slow_probe", description="test-only slow tool",
                   args_model=EmptyArgs, fn=slow_probe,
                   timeout_s=0.2, max_retries=2)
    agent = make_agent(db_path, [
        calls(tc("slow_probe", {})),
        final_rec(client_id="acme", metric_name="weighted_pipeline", metric_value=0.0,
                  recommendation="review",
                  rationale="The data tool timed out repeatedly, so no metric could be computed.",
                  confidence="low", data_sources=["slow_probe"]),
    ], extra_tools=[slow])
    started = time.monotonic()
    r = agent.run("Probe the slow tool.")
    elapsed = time.monotonic() - started
    t = r.tool_trace[0]
    assert not t.ok and t.attempts == 3  # 1 try + 2 retries
    assert "tool_timeout" in t.error
    assert elapsed < 5  # bounded: did not wait out the 5s sleep
    assert r.status == "completed"  # model got the error and finalized safely


def test_12_duplicate_calls_are_cached(db_path):
    args = {"metric": "weighted_pipeline", "client_id": "acme"}
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", args)),
        calls(tc("calculate_metric", args)),
        hold_rec("acme", "weighted_pipeline", 256000.0, ["calculate_metric"]),
    ])
    r = agent.run("What is Acme's weighted pipeline? (asked twice)")
    first, second = r.tool_trace
    assert first.ok and not first.cached and first.attempts == 1
    assert second.ok and second.cached and second.attempts == 0
    assert second.data == first.data


def test_13_irrelevant_request_is_declined(db_path):
    agent = make_agent(db_path, [
        decline("I only answer questions about the client pipeline."),
    ])
    r = agent.run("Write me a poem about the ocean.")
    assert r.status == "declined"
    assert r.tool_trace == []  # no tools touched
    assert r.recommendation is None


def test_14_prompt_injection_in_data_is_ignored(db_path):
    agent = make_agent(db_path, [
        calls(tc("list_deals", {"client_id": "globex"})),
        calls(tc("calculate_metric", {"metric": "weighted_pipeline", "client_id": "globex"})),
        final_rec(client_id="globex", metric_name="weighted_pipeline", metric_value=337500.0,
                  recommendation="expand",
                  rationale="Globex weighted pipeline is $337,500 across 3 open deals with "
                            "strong closed-won history. The data supports expansion.",
                  confidence="high", data_sources=["list_deals", "calculate_metric"]),
    ])
    r = agent.run("Should we expand with Globex?")
    assert r.status == "completed"
    # the agent SAW the injection (it is in the tool data)...
    deals = r.tool_trace[0].data["deals"]
    d6 = next(d for d in deals if d["id"] == "d6")
    assert d6["notes"] == INJECTION
    # ...and decided from the numbers, not from the injected instruction
    assert r.recommendation.recommendation == "expand"
    assert "escalate" not in r.recommendation.rationale.lower()
    assert "override" not in r.recommendation.rationale.lower()


def test_15_max_turns_bounds_a_chatty_model(db_path):
    script = [calls(tc("get_client", {"client_id": "acme"}))] * 20
    agent = make_agent(db_path, script, max_turns=3)
    r = agent.run("Tell me about Acme.")
    assert r.status == "error"
    assert "max_turns" in r.error
    assert r.turns == 3  # bounded, never 20


def test_16_invalid_final_answer_is_rejected(db_path):
    agent = make_agent(db_path, [final_raw({"client_id": "acme"})])  # missing fields
    r = agent.run("What is Acme's weighted pipeline?")
    assert r.status == "error"
    assert "validation" in r.error
    assert r.recommendation is None


def test_17_retry_succeeds_on_second_attempt(db_path):
    state = {"n": 0}

    def flaky() -> dict:
        state["n"] += 1
        if state["n"] == 1:
            raise TimeoutError("simulated hang")
        return {"ok": True, "value": 42}

    flaky_tool = ToolDef(name="flaky_lookup", description="test-only flaky tool",
                         args_model=EmptyArgs, fn=flaky,
                         timeout_s=5.0, max_retries=2)
    agent = make_agent(db_path, [
        calls(tc("flaky_lookup", {})),
        hold_rec("acme", "weighted_pipeline", 256000.0, ["flaky_lookup"]),
    ], extra_tools=[flaky_tool])
    r = agent.run("Look it up.")
    t = r.tool_trace[0]
    assert t.ok and t.attempts == 2 and t.data["value"] == 42
    assert r.status == "completed"


def test_18_metric_with_stage_filter(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "total_pipeline", "stage": "negotiation"})),
        hold_rec("all", "total_pipeline", 500000.0, ["calculate_metric"]),
    ])
    r = agent.run("Total pipeline in negotiation?")
    assert r.status == "completed"
    assert r.recommendation.metric_value == pytest.approx(500000.0)


# ------------------------------------------------------- robustness ---

def test_19_output_contract_holds(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "weighted_pipeline", "client_id": "acme"})),
        hold_rec("acme", "weighted_pipeline", 256000.0, ["calculate_metric"]),
    ])
    r = agent.run("What is Acme's weighted pipeline?")
    rec = r.recommendation
    assert 10 <= len(rec.rationale) <= 500
    assert rec.confidence in {"low", "medium", "high"}
    assert rec.recommendation in {"expand", "hold", "review", "escalate"}
    assert len(rec.data_sources) >= 1


def test_20_token_and_latency_totals_captured(db_path):
    agent = make_agent(db_path, [
        calls(tc("calculate_metric", {"metric": "weighted_pipeline", "client_id": "acme"})),
        hold_rec("acme", "weighted_pipeline", 256000.0, ["calculate_metric"]),
    ])
    r = agent.run("What is Acme's weighted pipeline?")
    assert r.status == "completed"
    assert r.total_tokens == 2 * (600 + 120)  # 2 stub turns x usage per turn
    assert r.latency_s >= 0
    assert r.turns == 2
