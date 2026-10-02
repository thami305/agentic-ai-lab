"""Lab 4 acceptance tests: checkpoint, interrupt, resume.

All deterministic, no network. The clock is injectable on CheckpointStore,
so TTL behavior is tested without sleeping.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab02.schemas import Packet
from lab02.validate import validate_brief
from lab03 import nodes as lab03_nodes
from lab03.policies import BadBriefPolicy, OraclePolicy
from lab03.state import BriefState
from lab04.checkpoint import (CheckpointStore, StaleCheckpointError,
                              UnknownRunError, state_from_dict, state_to_dict)
from lab04.interrupt import (InvalidDecisionError, InvalidEditError,
                             NotAwaitingApprovalError, build_interrupt_graph,
                             resume)
from lab04.policies import CountingPolicy, CrashPolicy
from lab04.runner import ResumeError, resume_run, run_persistent
from tests.conftest import QUESTION


# ------------------------------------------------------------- helpers ---

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class OneShotCrashPolicy(CountingPolicy):
    """Counts retrieve() calls and crashes exactly once in synthesize, so
    the resume can proceed with the same policy test-double."""

    def __init__(self):
        super().__init__()
        self._armed = True

    def synthesize(self, state):
        if self._armed:
            self._armed = False
            raise RuntimeError("simulated crash")
        return super().synthesize(state)


def fixed_clock(t: float):
    return lambda: t


# ------------------------------------------------- checkpoint basics ---

def test_checkpoint_file_exists_after_run_starts(packet, store):
    graph = build_interrupt_graph(OraclePolicy())
    state = BriefState(question=QUESTION, packet=packet)
    run_persistent(graph, state, store, "run-ck")
    assert (store.dir / "run-ck.json").exists()
    cp = store.load("run-ck")
    assert cp.run_id == "run-ck"
    assert cp.status == "awaiting_approval"
    assert cp.state.path == ["validate_input", "retrieve", "assess",
                             "synthesize", "validate", "await_approval"]


def test_checkpoint_roundtrip_preserves_state(packet, store):
    graph = build_interrupt_graph(OraclePolicy())
    state = BriefState(question=QUESTION, packet=packet)
    final = run_persistent(graph, state, store, "run-rt")
    cp = store.load("run-rt")
    assert cp.state.question == QUESTION
    assert cp.state.packet.topic == final.packet.topic
    assert cp.state.brief is not None
    assert [c.text for c in cp.state.brief.claims] == \
        [c.text for c in final.brief.claims]
    assert cp.state.path == final.path
    assert cp.state.tool_calls_made == final.tool_calls_made
    assert cp.state.total_tokens == final.total_tokens
    assert [p["passage_id"] for p in cp.state.passages] == \
        [p["passage_id"] for p in final.passages]


def test_resume_unknown_run_id_fails(store):
    with pytest.raises(UnknownRunError):
        store.load("no-such-run")
    with pytest.raises(UnknownRunError):
        resume("no-such-run", "approve", store)


# ------------------------------------------------------------- approve ---

def test_approve_publishes(packet, store, paused):
    decision = resume("run-1", "approve", store)
    assert decision == "approve"
    cp = store.load("run-1")
    assert cp.status == "decided"
    assert cp.decision == "approve"
    assert cp.state.terminal == "publish"
    assert "published" in cp.state.terminal_reason


def test_approval_decision_is_logged(store, paused):
    resume("run-1", "approve", store)
    records = read_jsonl(store.dir / "decisions.jsonl")
    assert len(records) == 1
    rec = records[0]
    assert rec["run_id"] == "run-1"
    assert rec["decision"] == "approve"
    assert rec["edited"] is False
    assert isinstance(rec["at"], (int, float))


def test_approve_publishes_side_effect_exactly_once(store, paused):
    resume("run-1", "approve", store)
    records = store.side_effect_records("run-1")
    assert len(records) == 1
    assert records[0]["action"] == "publish"


# ------------------------------------------------------ reject/abandon ---

def test_reject_marks_rejected_and_publishes_nothing(store, paused):
    decision = resume("run-1", "reject", store)
    assert decision == "reject"
    cp = store.load("run-1")
    assert cp.state.terminal == "review"
    assert "rejected" in cp.state.terminal_reason
    assert store.side_effect_records("run-1") == []
    assert store.decision_records("run-1")[0]["decision"] == "reject"


def test_abandon_discards_run(store, paused):
    decision = resume("run-1", "abandon", store)
    assert decision == "abandon"
    cp = store.load("run-1")
    assert cp.state.terminal == "stop"
    assert "abandoned" in cp.state.terminal_reason
    assert store.side_effect_records("run-1") == []


def test_invalid_decision_rejected(store, paused):
    with pytest.raises(InvalidDecisionError):
        resume("run-1", "maybe", store)
    # Still paused: the bad decision changed nothing.
    assert store.load("run-1").status == "awaiting_approval"


# ------------------------------------------------------- edit/approve ---

def test_edit_and_approve_with_valid_edit_publishes(store, paused):
    cp = store.load("run-1")
    edited = cp.state.brief.model_copy(deep=True)
    edited.claims[0].text = edited.claims[0].text + " (confirmed by reviewer)"
    assert validate_brief(edited, cp.state.packet).ok

    decision = resume("run-1", "approve", store, edited_brief=edited)
    assert decision == "approve"
    done = store.load("run-1")
    assert done.state.terminal == "publish"
    assert "(confirmed by reviewer)" in done.state.brief.claims[0].text
    assert store.decision_records("run-1")[0]["edited"] is True
    assert len(store.side_effect_records("run-1")) == 1


def test_edit_and_approve_with_invalid_edit_stays_awaiting(store, paused):
    cp = store.load("run-1")
    edited = cp.state.brief.model_copy(deep=True)
    edited.claims[0].evidence[0].quote = "fabricated quote"
    assert not validate_brief(edited, cp.state.packet).ok

    with pytest.raises(InvalidEditError):
        resume("run-1", "approve", store, edited_brief=edited)
    # Fails closed on the edit: still awaiting, nothing published, nothing
    # logged.
    still = store.load("run-1")
    assert still.status == "awaiting_approval"
    assert still.state.terminal == "await_approval"
    assert store.side_effect_records("run-1") == []
    assert store.decision_records("run-1") == []


def test_edit_requires_approve_decision(store, paused):
    cp = store.load("run-1")
    edited = cp.state.brief.model_copy(deep=True)
    with pytest.raises(InvalidDecisionError):
        resume("run-1", "reject", store, edited_brief=edited)
    assert store.load("run-1").status == "awaiting_approval"


# ------------------------------------------------- duplicate idempotency ---

def test_duplicate_resume_is_idempotent(store, paused):
    first = resume("run-1", "approve", store)
    second = resume("run-1", "approve", store)
    assert first == "approve"
    assert second == "approve"  # returns the already-logged decision
    assert len(store.decision_records("run-1")) == 1
    assert len(store.side_effect_records("run-1")) == 1


def test_second_decision_does_not_override_first(store, paused):
    resume("run-1", "reject", store)
    assert resume("run-1", "approve", store) == "reject"
    assert store.load("run-1").state.terminal == "review"
    assert store.side_effect_records("run-1") == []


# ------------------------------------------------------------ TTL/close ---

def test_expired_checkpoint_fails_closed(packet, tmp_path):
    store = CheckpointStore(tmp_path / "cp", ttl_seconds=60,
                            now_fn=fixed_clock(1000.0))
    graph = build_interrupt_graph(OraclePolicy())
    run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                   store, "run-ttl")

    aged = CheckpointStore(tmp_path / "cp", ttl_seconds=60,
                           now_fn=fixed_clock(2000.0))
    with pytest.raises(StaleCheckpointError):
        aged.load("run-ttl")
    with pytest.raises(StaleCheckpointError):
        resume("run-ttl", "approve", aged)
    # Fails closed: nothing published, nothing decided.
    assert aged.side_effect_records("run-ttl") == []
    assert aged.decision_records("run-ttl") == []


def test_ttl_boundary_just_inside_loads_fine(packet, tmp_path):
    store = CheckpointStore(tmp_path / "cp", ttl_seconds=60,
                            now_fn=fixed_clock(1000.0))
    graph = build_interrupt_graph(OraclePolicy())
    run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                   store, "run-edge")

    inside = CheckpointStore(tmp_path / "cp", ttl_seconds=60,
                             now_fn=fixed_clock(1059.0))
    cp = inside.load("run-edge")
    assert cp.status == "awaiting_approval"
    assert resume("run-edge", "approve", inside) == "approve"


# --------------------------------------------------------------- crash ---

def test_crash_keeps_last_completed_checkpoint(packet, tmp_path):
    store = CheckpointStore(tmp_path / "cp")
    graph = build_interrupt_graph(CrashPolicy())
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                       store, "run-crash")
    cp = store.load("run-crash")
    assert cp.status == "running"
    assert cp.next_node == "synthesize"
    # The on-disk checkpoint is from the last COMPLETED node (assess):
    # "synthesize" was noted in memory but never checkpointed.
    assert cp.state.path == ["validate_input", "retrieve", "assess"]
    assert len(cp.state.passages) > 0  # retrieve completed before the crash


def test_crash_then_resume_preserves_evidence(packet, tmp_path):
    store = CheckpointStore(tmp_path / "cp")
    graph = build_interrupt_graph(CrashPolicy())
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                       store, "run-crash")
    pre_crash_ids = [p["passage_id"]
                     for p in store.load("run-crash").state.passages]

    # Fresh process: brand-new store instance and a new graph with a working
    # policy. The checkpointed passages must be reused as-is.
    fresh_store = CheckpointStore(tmp_path / "cp")
    final = resume_run("run-crash", fresh_store, build_interrupt_graph,
                       OraclePolicy())
    assert final.terminal == "await_approval"
    resumed_ids = [p["passage_id"] for p in final.passages]
    assert resumed_ids == pre_crash_ids
    assert validate_brief(final.brief, packet).ok
    evidence_ids = {e.passage_id for c in final.brief.claims
                    for e in c.evidence}
    assert evidence_ids <= set(pre_crash_ids)  # evidence intact


def test_resume_does_not_reexecute_retrieve(packet, tmp_path):
    policy = OneShotCrashPolicy()
    store = CheckpointStore(tmp_path / "cp")
    graph = build_interrupt_graph(policy)
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                       store, "run-count")
    assert policy.retrieve_count == 1

    fresh_store = CheckpointStore(tmp_path / "cp")
    final = resume_run("run-count", fresh_store, build_interrupt_graph, policy)
    assert final.terminal == "await_approval"
    assert policy.retrieve_count == 1  # retrieve not re-executed on resume


def test_resume_run_refuses_finished_run(packet, store):
    graph = lab03_nodes.build_graph(OraclePolicy())
    final = run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                           store, "run-done")
    assert final.terminal == "publish"
    with pytest.raises(ResumeError):
        resume_run("run-done", store, lab03_nodes.build_graph, OraclePolicy())


def test_resume_decision_when_not_awaiting_approval(packet, tmp_path):
    store = CheckpointStore(tmp_path / "cp")
    graph = build_interrupt_graph(CrashPolicy())
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                       store, "run-mid")
    # The run is mid-flight (status=running), not paused for approval.
    with pytest.raises(NotAwaitingApprovalError):
        resume("run-mid", "approve", store)


def test_review_branch_has_no_approval_interrupt(packet, store):
    # A validation failure routes to review, not to the interrupt.
    graph = build_interrupt_graph(BadBriefPolicy())
    final = run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                           store, "run-review")
    assert final.terminal == "review"
    assert store.load("run-review").status == "finished"
