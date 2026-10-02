"""Persistent graph runner for Lab 4.

run_persistent replicates lab03 Graph.run's loop (record node in state.path,
run node.fn, follow the router, stop at terminal nodes) but checkpoints the
full BriefState to the CheckpointStore after EVERY node. If a node fn raises,
the exception propagates to the caller and the checkpoint from the last
completed node remains on disk: save happens after each successful node, so
the crash can never leave a half-written node state behind.

resume_run loads a checkpoint with a fresh store (the "fresh process"
simulation: new CheckpointStore instance, new graph built by graph_factory)
and continues the loop from the recorded next_node. It fails closed on
missing or stale checkpoints and refuses to resume runs that already
finished.
"""
from __future__ import annotations

from typing import Callable

from lab03.graph import Graph
from lab03.state import BriefState

from .checkpoint import CheckpointStore


class ResumeError(Exception):
    """A run cannot be continued from its checkpoint."""


def run_persistent(graph: Graph, state: BriefState, store: CheckpointStore,
                   run_id: str, start_node: str | None = None) -> BriefState:
    if graph.entry not in graph.nodes:
        raise ValueError(f"unknown entry node '{graph.entry}'")
    current = start_node or graph.entry
    steps = 0
    while True:
        steps += 1
        if steps > graph.max_steps:
            raise RuntimeError(
                f"graph exceeded max_steps={graph.max_steps} "
                f"(path: {' -> '.join(state.path)})")
        node = graph.nodes.get(current)
        if node is None:
            raise ValueError(f"router named unknown node '{current}'")
        state.note(node.name)
        # If node.fn raises, the exception propagates and the checkpoint
        # from the last completed node stays on disk (it was saved below,
        # after that node's router ran).
        node.fn(state)
        if node.router is None:
            if node.terminal is None:
                raise ValueError(
                    f"node '{node.name}' is terminal but sets no terminal state")
            state.terminal = node.terminal
            if state.terminal_reason is None:
                state.terminal_reason = node.terminal
            status = ("awaiting_approval" if node.terminal == "await_approval"
                      else "finished")
            store.save(run_id, state, next_node=None, status=status)
            return state
        current = node.router(state)
        store.save(run_id, state, next_node=current, status="running")


def resume_run(run_id: str, store: CheckpointStore,
               graph_factory: Callable[[object], Graph],
               policy: object) -> BriefState:
    """Continue a crashed run from its checkpoint.

    load() fails closed on a missing or stale checkpoint. Runs that already
    reached a terminal state (finished, decided, awaiting_approval) have
    nothing to continue and raise ResumeError.
    """
    checkpoint = store.load(run_id)
    if checkpoint.status in ("finished", "decided", "awaiting_approval"):
        raise ResumeError(
            f"run {run_id!r} has status {checkpoint.status!r}: "
            "nothing to resume")
    if not checkpoint.next_node:
        raise ResumeError(
            f"run {run_id!r} has no next_node recorded: cannot resume")
    graph = graph_factory(policy)
    return run_persistent(graph, checkpoint.state, store, run_id,
                          start_node=checkpoint.next_node)
