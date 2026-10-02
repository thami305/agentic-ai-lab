"""Pattern A — single agent with tools (lab-01-style loop).

One AgentLoop, the full proposal registry, one review request. The seeded
stub proposes tool calls and the final Review; the loop enforces the
allow-list, argument validation, and both budgets; deterministic
post-validation (validate_review) decides whether the review ships.
"""
from __future__ import annotations

import time

from lab02.models import ModelBackend

from .common import PatternResult, finalize
from .loop import AgentLoop, LoopConfig
from .proposal import Proposal, load_proposal
from .schemas import Review
from .seeded import OracleStub, SeededStub
from .tools import build_registry
from .validate import validate_review

QUESTION = ("Review this vendor proposal and produce a structured review: "
            "verdict (accept/revise/reject), findings with severity and "
            "verbatim evidence, and risks.")


def run_pattern_a(seed: int, backend: ModelBackend | None = None,
                  proposal: Proposal | None = None,
                  config: LoopConfig | None = None) -> PatternResult:
    proposal = proposal or load_proposal()
    backend = backend or SeededStub(seed)
    started = time.monotonic()
    loop = AgentLoop(backend, build_registry(proposal),
                     config or LoopConfig())
    res = loop.run(QUESTION, Review,
                   validator=lambda r: validate_review(r, proposal))
    latency = time.monotonic() - started
    review = res.final if isinstance(res.final, Review) else None
    return finalize("A", seed, review, res.tool_trace, res.tool_calls_made,
                    res.total_tokens, latency, proposal,
                    error=None if res.status == "completed" else res.error)


def run_pattern_a_oracle(proposal: Proposal | None = None) -> PatternResult:
    """Deterministic oracle run for the correctness tests (no randomness)."""
    return run_pattern_a(seed=0, backend=OracleStub(), proposal=proposal)
