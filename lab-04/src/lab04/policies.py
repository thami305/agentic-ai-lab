"""Lab 4 policies: crash injection and tool-call counting.

Both extend lab03's deterministic OraclePolicy, so every run stays
reproducible while tests can inject failures and count tool executions.
"""
from __future__ import annotations

from typing import Any

from lab02.schemas import ResearchBrief
from lab03.policies import OraclePolicy
from lab03.state import BriefState


class CrashPolicy(OraclePolicy):
    """Retrieves normally, then raises in synthesize: the crash lands AFTER
    retrieve has completed and been checkpointed, so the resume path must
    reuse the checkpointed passages instead of re-running retrieval."""

    def synthesize(self, state: BriefState) -> ResearchBrief:
        raise RuntimeError("simulated crash")


class CountingPolicy(OraclePolicy):
    """Counts retrieve() executions. After a crash-and-resume the counter
    must not have increased: proof that the resumed run reused the
    checkpointed retrieval result instead of re-executing the tool."""

    def __init__(self):
        self.retrieve_count = 0

    def retrieve(self, state: BriefState) -> list[dict[str, Any]]:
        self.retrieve_count += 1
        return super().retrieve(state)
