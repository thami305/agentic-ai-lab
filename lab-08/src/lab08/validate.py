"""Deterministic post-validation for Lab 8 reviews.

The model proposes; this code decides whether the review may ship. Checks:

1. Every finding's evidence names a real proposal passage id.
2. Every quote is a verbatim substring of the cited passage (whitespace
   normalized) — paraphrases and fabricated quotes fail.
3. The verdict is sane: a review with any high-severity finding may not
   conclude "accept".

verdict_for() is the deterministic verdict rule every pattern shares:
any high-severity finding rules out "accept"; three or more highs escalate
to "reject". The seeded stubs jitter only inside the sane set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .issues import Issue
from .proposal import Proposal
from .schemas import Finding, Review


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ValidationReport:
    ok: bool
    violations: list[str] = field(default_factory=list)


def validate_review(review: Review, proposal: Proposal) -> ValidationReport:
    violations: list[str] = []

    if not review.findings:
        violations.append("review has no findings")

    for i, f in enumerate(review.findings):
        tag = f"finding[{i}]"
        passage = proposal.by_id(f.evidence.passage_id)
        if passage is None:
            violations.append(
                f"{tag}: unknown passage_id '{f.evidence.passage_id}'")
            continue
        if _norm(f.evidence.quote) not in _norm(passage.text):
            violations.append(
                f"{tag}: quote is not a verbatim substring of passage "
                f"'{f.evidence.passage_id}' — fabricated or altered citation")

    if any(f.severity == "high" for f in review.findings) \
            and review.verdict == "accept":
        violations.append(
            "verdict 'accept' is not sane: the review contains high-severity "
            "findings")

    if not review.risks:
        violations.append("review has no risks")

    return ValidationReport(ok=not violations, violations=violations)


def verdict_for(findings: list[Finding] | list[Issue]) -> str:
    """Deterministic verdict rule shared by all patterns."""
    highs = sum(1 for f in findings if f.severity == "high")
    mediums = sum(1 for f in findings if f.severity == "medium")
    if highs >= 3:
        return "reject"
    if highs >= 1 or mediums >= 1:
        return "revise"
    return "accept"


def unsupported_claims(review: Review, proposal: Proposal) -> int:
    """Number of findings with at least one citation violation — the
    'unsupported claims' metric the measurement harness reports."""
    bad = 0
    for f in review.findings:
        passage = proposal.by_id(f.evidence.passage_id)
        if passage is None or _norm(f.evidence.quote) not in _norm(passage.text):
            bad += 1
    return bad
