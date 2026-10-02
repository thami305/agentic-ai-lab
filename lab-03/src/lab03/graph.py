"""Minimal graph runtime for Lab 3.

Nodes are named steps with a declared kind — "deterministic" (pure code:
validation, routing checks, state inspection) or "model" (calls a model or a
model-driven policy). Edges are conditional: each non-terminal node names a
router function, a pure function of state returning the next node name.

The runtime records the path taken on the state itself, caps total steps
against cycles, and fails loudly on a missing node or a router that names
one. Terminal nodes set state.terminal and stop the run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from .state import BriefState, Terminal

NodeKind = Literal["deterministic", "model"]
NodeFn = Callable[[BriefState], None]
RouterFn = Callable[[BriefState], str]


@dataclass
class Node:
    name: str
    kind: NodeKind
    fn: NodeFn
    router: RouterFn | None = None  # None = terminal node
    terminal: Terminal | None = None


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    entry: str = ""
    max_steps: int = 50

    def add(self, node: Node) -> None:
        self.nodes[node.name] = node

    def run(self, state: BriefState) -> BriefState:
        if self.entry not in self.nodes:
            raise ValueError(f"unknown entry node '{self.entry}'")
        current = self.entry
        steps = 0
        while True:
            steps += 1
            if steps > self.max_steps:
                raise RuntimeError(
                    f"graph exceeded max_steps={self.max_steps} "
                    f"(path: {' -> '.join(state.path)})")
            node = self.nodes.get(current)
            if node is None:
                raise ValueError(f"router named unknown node '{current}'")
            state.note(node.name)
            node.fn(state)
            if node.router is None:
                if node.terminal is None:
                    raise ValueError(
                        f"node '{node.name}' is terminal but sets no terminal state")
                state.terminal = node.terminal
                if state.terminal_reason is None:
                    state.terminal_reason = node.terminal
                return state
            current = node.router(state)
