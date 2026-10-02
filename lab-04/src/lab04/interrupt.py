"""Approval interrupt for Lab 4.

build_interrupt_graph takes lab03's graph and REPLACES the "publish"
terminal with an "await_approval" terminal node: the validate node's router
is wrapped so a "publish" routing decision now lands on await_approval, and
the old publish node is removed so nothing can route to it by accident.
When the runner reaches await_approval it saves the checkpoint with
status="awaiting_approval" and stops: the run is paused, not finished.

resume(run_id, decision, store, edited_brief=None) applies the human call:

- approve: mark published, append ONE side-effect record keyed by run_id.
- reject: mark reviewed-as-rejected, nothing published.
- abandon: mark stopped-as-abandoned, nothing published.
- edit-and-approve: edited_brief is re-validated with lab02 validate_brief;
  an invalid edit raises InvalidEditError and the run STAYS
  awaiting_approval; a valid edit replaces state.brief and publishes.

Every decision is appended to decisions.jsonl as
{run_id, decision, at, edited}. Duplicate resume is idempotent: once a run
is "decided", resume returns the already-logged decision without touching
the side-effect log again (the first decision wins).
"""
from __future__ import annotations

from lab02.schemas import ResearchBrief
from lab02.validate import validate_brief
from lab03 import nodes as lab03_nodes
from lab03.graph import Graph, Node
from lab03.policies import Policy
from lab03.state import BriefState

from .checkpoint import CheckpointStore


DECISIONS = ("approve", "reject", "abandon")


class ResumeDecisionError(Exception):
    """Base class for approval-resume failures."""


class InvalidDecisionError(ResumeDecisionError):
    """Decision not in {"approve", "reject", "abandon"}, or edited_brief
    supplied with a non-approve decision."""


class NotAwaitingApprovalError(ResumeDecisionError):
    """The run is not paused at the approval interrupt."""


class InvalidEditError(ResumeDecisionError):
    """The edited brief failed validation: the run stays awaiting_approval."""


def await_approval(state: BriefState) -> None:
    n = len(state.brief.claims) if state.brief else 0
    state.terminal_reason = (
        f"awaiting approval: brief with {n} grounded claims; "
        "human decision required.")


def build_interrupt_graph(policy: Policy | None = None) -> Graph:
    """lab03's graph with the publish terminal replaced by await_approval."""
    graph = lab03_nodes.build_graph(policy)
    validate_node = graph.nodes["validate"]
    original_router = validate_node.router

    def router_after_validate(state: BriefState) -> str:
        nxt = original_router(state)
        return "await_approval" if nxt == "publish" else nxt

    validate_node.router = router_after_validate
    del graph.nodes["publish"]
    graph.add(Node("await_approval", "deterministic", await_approval,
                   terminal="await_approval"))
    return graph


def resume(run_id: str, decision: str, store: CheckpointStore,
           edited_brief: ResearchBrief | None = None) -> str:
    """Apply a human approval decision to a paused run. Returns the decision
    that took effect (for duplicate resumes, the already-logged one)."""
    if decision not in DECISIONS:
        raise InvalidDecisionError(
            f"unknown decision {decision!r}; expected one of {DECISIONS}")
    checkpoint = store.load(run_id)  # fails closed on missing/stale
    if checkpoint.status == "decided":
        # Idempotent duplicate resume: the first decision already took
        # effect; return it without re-applying side effects.
        return checkpoint.decision
    if checkpoint.status != "awaiting_approval":
        raise NotAwaitingApprovalError(
            f"run {run_id!r} has status {checkpoint.status!r}; "
            "expected 'awaiting_approval'")
    state = checkpoint.state

    edited = False
    if edited_brief is not None:
        if decision != "approve":
            raise InvalidDecisionError(
                "edited_brief is only valid with decision='approve'")
        report = validate_brief(edited_brief, state.packet)
        if not report.ok:
            # Stay awaiting_approval: checkpoint untouched, nothing logged.
            raise InvalidEditError(
                "edited brief failed validation; staying awaiting_approval: "
                + "; ".join(report.violations))
        state.brief = edited_brief
        edited = True

    if decision == "approve":
        n = len(state.brief.claims) if state.brief else 0
        state.terminal = "publish"
        state.terminal_reason = f"published: brief with {n} grounded claims."
        state.note("publish")
        # Side effect, applied at most once per run_id: the log check is
        # what makes a duplicate resume safe.
        store.record_side_effect(run_id, {
            "run_id": run_id,
            "action": "publish",
            "claims": n,
            "edited": edited,
            "at": store.now_fn(),
        })
    elif decision == "reject":
        state.terminal = "review"
        state.terminal_reason = (
            "rejected by human approver: brief not published.")
        state.note("review")
    else:  # abandon
        state.terminal = "stop"
        state.terminal_reason = (
            "abandoned by human approver: run discarded.")
        state.note("stop")

    store.log_decision(run_id, decision, edited)
    store.save(run_id, state, next_node=None, status="decided",
               decision=decision, edited=edited)
    return decision
