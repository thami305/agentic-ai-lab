"""Lab 3 shared state: one typed object every node reads and writes.

The state is the inspectable record of the run: what was retrieved, what was
decided, which path was taken, and where it terminated. Tests assert on it
directly — no hidden control flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from lab02.schemas import Packet, ResearchBrief

Terminal = Literal["clarify", "review", "publish", "stop"]


@dataclass
class BriefState:
    question: str
    packet: Packet
    # retrieval
    passages: list[dict[str, Any]] = field(default_factory=list)
    retrieval_retries: int = 0
    # synthesis + validation
    brief: ResearchBrief | None = None
    validation_violations: list[str] = field(default_factory=list)
    conflict_detail: str | None = None
    # terminals
    terminal: Terminal | None = None
    terminal_reason: str | None = None
    # observability
    path: list[str] = field(default_factory=list)
    tool_calls_made: int = 0
    total_tokens: int = 0

    def note(self, node: str) -> None:
        self.path.append(node)

    def terminate(self, terminal: Terminal, reason: str) -> None:
        self.terminal = terminal
        self.terminal_reason = reason
        self.note(terminal)
