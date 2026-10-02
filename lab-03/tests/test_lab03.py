"""Lab 3 acceptance tests — the graph, its branches, and its terminals.

Every test asserts on the recorded path and the inspectable state: which
nodes ran, what they mutated, and which intentional terminal state won.
"""
from __future__ import annotations

import pytest

from lab02.validate import validate_brief
from lab03.graph import Graph, Node
from lab03.nodes import (MAX_RETRIEVAL_RETRIES, build_graph, detect_conflict,
                         route_after_assess, route_after_input,
                         route_after_retrieve, route_after_validate)
from lab03.policies import BadBriefPolicy, FlakyPolicy, OraclePolicy
from lab03.state import BriefState
from tests.conftest import run_question

Q1 = "How utilized is Northwind's current warehouse?"
Q_CONFLICT = "When does finance expect the second site to break even?"
Q_NOHIT = "What is the CEO's total compensation?"


# ------------------------------------------------------------ paths ---

def test_happy_path_reaches_publish(graph, packet):
    state = run_question(graph, packet, Q1)
    assert state.path == ["validate_input", "retrieve", "assess",
                          "synthesize", "validate", "publish"]
    assert state.terminal == "publish"
    assert state.brief is not None
    assert validate_brief(state.brief, packet).ok


def test_empty_question_routes_to_clarify(graph, packet):
    state = run_question(graph, packet, "   ")
    assert state.path == ["validate_input", "clarify"]
    assert state.terminal == "clarify"
    assert "empty" in state.terminal_reason


def test_unanswerable_routes_to_clarify(graph, packet):
    state = run_question(graph, packet, Q_NOHIT)
    assert state.path == ["validate_input", "retrieve", "assess", "clarify"]
    assert state.terminal == "clarify"
    assert state.brief is None


def test_conflicting_evidence_routes_to_review(graph, packet):
    state = run_question(graph, packet, Q_CONFLICT)
    assert state.path == ["validate_input", "retrieve", "assess", "review"]
    assert state.terminal == "review"
    assert state.conflict_detail is not None
    assert "conflicting evidence" in state.terminal_reason


def test_repeated_tool_failure_routes_to_stop(packet):
    graph = build_graph(FlakyPolicy(fail_times=99))
    state = run_question(graph, packet, Q1)
    assert state.path == ["validate_input", "retrieve", "stop"]
    assert state.terminal == "stop"
    assert state.retrieval_retries == MAX_RETRIEVAL_RETRIES + 1
    assert "graceful stop" in state.terminal_reason


def test_retry_then_success_publishes(packet):
    graph = build_graph(FlakyPolicy(fail_times=2))
    state = run_question(graph, packet, Q1)
    assert state.terminal == "publish"
    assert state.retrieval_retries == 2
    assert state.brief is not None


def test_validation_failure_routes_to_review(packet):
    graph = build_graph(BadBriefPolicy())
    state = run_question(graph, packet, Q1)
    assert state.path == ["validate_input", "retrieve", "assess",
                          "synthesize", "validate", "review"]
    assert state.terminal == "review"
    assert state.validation_violations
    assert "post-validation" in state.terminal_reason


# --------------------------------------------------- state inspection ---

def test_state_mutations_are_inspectable(graph, packet):
    state = run_question(graph, packet, Q1)
    assert len(state.passages) == 3
    assert all("text" in p and "passage_id" in p for p in state.passages)
    assert state.brief.question == Q1
    assert state.tool_calls_made >= 1
    assert state.total_tokens > 0


def test_every_terminal_state_reachable(packet):
    cases = {
        "publish": (build_graph(), Q1),
        "clarify": (build_graph(), ""),
        "review": (build_graph(), Q_CONFLICT),
        "stop": (build_graph(FlakyPolicy(fail_times=99)), Q1),
    }
    for terminal, (graph, question) in cases.items():
        state = run_question(graph, packet, question)
        assert state.terminal == terminal, (terminal, state.path)


# ------------------------------------------------------------ routers ---

def test_router_after_input(packet):
    assert route_after_input(BriefState(question="", packet=packet)) == "clarify"
    assert route_after_input(BriefState(question=Q1, packet=packet)) == "retrieve"


def test_router_after_assess_branches(packet):
    s = BriefState(question=Q1, packet=packet)
    assert route_after_assess(s) == "clarify"  # no passages
    s.passages = [{"text": "warehouse at 92% utilization"}]
    assert route_after_assess(s) == "synthesize"


def test_router_after_retrieve(packet):
    s = BriefState(question=Q1, packet=packet)
    assert route_after_retrieve(s) == "assess"
    s.retrieval_retries = MAX_RETRIEVAL_RETRIES + 1
    assert route_after_retrieve(s) == "stop"


def test_router_after_validate(packet):
    s = BriefState(question=Q1, packet=packet)
    assert route_after_validate(s) == "publish"
    s.validation_violations = ["bad quote"]
    assert route_after_validate(s) == "review"


def test_detect_conflict_finds_revision_pair(packet):
    s = BriefState(question=Q_CONFLICT, packet=packet)
    s.passages = [
        {"text": "Finance projects break-even on the second site within 14 months."},
        {"text": "Revised finance note: break-even extends to 22 months, "
                 "superseding the earlier estimate."},
    ]
    assert detect_conflict(s) is not None


def test_detect_conflict_clean_passages(packet):
    s = BriefState(question=Q1, packet=packet)
    s.passages = [{"text": "The warehouse is operating at 92% utilization."}]
    assert detect_conflict(s) is None


# -------------------------------------------------- graph guarantees ---

def test_node_kinds_declared(graph):
    kinds = {n.name: n.kind for n in graph.nodes.values()}
    assert kinds["validate_input"] == "deterministic"
    assert kinds["assess"] == "deterministic"
    assert kinds["validate"] == "deterministic"
    assert kinds["retrieve"] == "model"
    assert kinds["synthesize"] == "model"


def test_unknown_entry_fails_loudly(packet):
    g = Graph(entry="nope")
    with pytest.raises(ValueError, match="unknown entry node"):
        g.run(BriefState(question=Q1, packet=packet))


def test_router_naming_unknown_node_fails_loudly(packet):
    g = Graph(entry="a")
    g.add(Node("a", "deterministic", lambda s: None,
               router=lambda s: "missing"))
    with pytest.raises(ValueError, match="unknown node"):
        g.run(BriefState(question=Q1, packet=packet))


def test_terminal_without_state_fails_loudly(packet):
    g = Graph(entry="a")
    g.add(Node("a", "deterministic", lambda s: None))  # no router, no terminal
    with pytest.raises(ValueError, match="terminal but sets no terminal"):
        g.run(BriefState(question=Q1, packet=packet))
