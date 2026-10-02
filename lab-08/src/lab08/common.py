"""Shared result type and metric helpers for the three patterns.

Metric definitions (used identically by evaluate.py and the tests):

- task success: the run produced a schema-valid Review AND every finding
  cites a real passage with a verbatim quote (validate_review ok).
- tool accuracy: fraction of *successful* get_passage-family calls
  (get_passage, get_pricing_passage, get_terms_passage) whose passage_id
  appears in at least one finding's evidence. 1.0 when the run made no
  such calls (vacuous — nothing was mis-cited).
- unsupported claims: number of findings with a citation violation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schemas import Review
from .validate import unsupported_claims, validate_review

GET_PASSAGE_TOOLS = frozenset(
    {"get_passage", "get_pricing_passage", "get_terms_passage"})


@dataclass
class PatternResult:
    pattern: str            # "A" | "B" | "C"
    seed: int
    review: Review | None
    success: bool           # schema-valid AND all findings cited
    verdict_sane: bool      # not "accept" while a high finding is present
    tool_accuracy: float
    unsupported: int        # unsupported claims count
    tool_calls: int
    tokens: int
    latency_s: float
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def tool_accuracy(trace: list[Any], review: Review | None) -> float:
    cited = {f.evidence.passage_id for f in review.findings} if review else set()
    calls = [t for t in trace
             if getattr(t, "name", None) in GET_PASSAGE_TOOLS and t.ok]
    if not calls:
        return 1.0
    hit = sum(1 for t in calls if t.arguments.get("passage_id") in cited)
    return hit / len(calls)


def verdict_sane(review: Review | None) -> bool:
    if review is None:
        return False
    return not (review.verdict == "accept"
                and any(f.severity == "high" for f in review.findings))


def finalize(pattern: str, seed: int, review: Review | None,
             trace: list[Any], tool_calls: int, tokens: int,
             latency_s: float, proposal, error: str | None = None,
             extra: dict[str, Any] | None = None) -> PatternResult:
    if review is not None:
        report = validate_review(review, proposal)
        success = report.ok
        unsup = unsupported_claims(review, proposal)
    else:
        success, unsup = False, 0
    return PatternResult(
        pattern=pattern, seed=seed, review=review, success=success,
        verdict_sane=verdict_sane(review),
        tool_accuracy=tool_accuracy(trace, review), unsupported=unsup,
        tool_calls=tool_calls, tokens=tokens, latency_s=latency_s,
        error=error, extra={"trace_names": [getattr(t, "name", "?")
                                            for t in trace],
                            **(extra or {})})
