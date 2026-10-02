"""Model-driven policies for Lab 3.

The graph declares retrieve/synthesize as "model" nodes; in production they
would call a real backend. Here the default policy is the deterministic
oracle ported from Lab 2 (same retrieval, same brief construction), so every
run is reproducible. Tests inject failing policies to exercise retries and
the graceful-stop branch.
"""
from __future__ import annotations

import re
from typing import Any, Protocol

from lab02.schemas import Claim, Evidence, ResearchBrief
from lab02.tools import keywords, score_passage
from lab02.packet import all_passages

from .state import BriefState


class Policy(Protocol):
    def retrieve(self, state: BriefState) -> list[dict[str, Any]]: ...
    def synthesize(self, state: BriefState) -> ResearchBrief: ...


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


_JUDGMENT_WORDS = frozenset(
    "should recommend best worst will next decide decision choose optimal".split())


class OraclePolicy:
    """Deterministic stand-in for the model: keyword search, top-3 passages,
    claims from verbatim first sentences."""

    def retrieve(self, state: BriefState) -> list[dict[str, Any]]:
        keys = keywords(state.question)
        scored = [(score_passage(keys, p.text), s, p)
                  for s, p in all_passages(state.packet)]
        scored = [(sc, s, p) for sc, s, p in scored if sc > 0]
        scored.sort(key=lambda t: (-t[0], t[1].id, t[2].pid))
        state.tool_calls_made += 1  # one logical retrieval round
        return [{"source_id": s.id, "source_title": s.title,
                 "passage_id": p.pid, "text": p.text}
                for sc, s, p in scored[:3]]

    def synthesize(self, state: BriefState) -> ResearchBrief:
        claims = [Claim(text=_first_sentence(p["text"]),
                        evidence=[Evidence(source_id=p["source_id"],
                                           passage_id=p["passage_id"],
                                           quote=_first_sentence(p["text"]))])
                  for p in state.passages]
        sources_used = sorted({p["source_id"] for p in state.passages})
        open_questions: list[str] = []
        if set(keywords(state.question)) & _JUDGMENT_WORDS:
            open_questions.append(
                "The packet provides evidence but no decision: the go/no-go "
                "call needs board sign-off beyond these documents.")
        lowered = state.question.lower()
        if "where" in set(keywords(state.question)) or "which location" in lowered:
            open_questions.append("The packet names no candidate site locations.")
        state.total_tokens += 1100  # deterministic stub accounting
        return ResearchBrief(question=state.question, claims=claims,
                             assumptions=[], open_questions=open_questions,
                             sources_used=sources_used)


class FlakyPolicy(OraclePolicy):
    """Fails retrieve() fail_times times before succeeding — exercises the
    bounded-retry branch deterministically."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.attempts = 0

    def retrieve(self, state: BriefState) -> list[dict[str, Any]]:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError("simulated tool failure")
        return super().retrieve(state)


class BadBriefPolicy(OraclePolicy):
    """Synthesizes a brief with a fabricated quote — exercises the
    validation-failure branch."""

    def synthesize(self, state: BriefState) -> ResearchBrief:
        brief = super().synthesize(state)
        if brief.claims:
            brief.claims[0].evidence[0].quote = "fabricated evidence"
        return brief
