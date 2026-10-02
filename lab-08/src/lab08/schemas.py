"""Lab 8 schemas — every boundary crossing is typed and validated.

The review is the product: every finding must cite a real proposal passage
with a verbatim quote, and the deterministic post-validator (validate.py)
checks every citation before the review may ship.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """One citation: which proposal passage, and the exact quoted text."""

    passage_id: str = Field(min_length=1, max_length=32)
    quote: str = Field(min_length=1, max_length=1000)


class Finding(BaseModel):
    """One review finding. The claim is the reviewer's judgment; the evidence
    is the verbatim proposal text it rests on."""

    claim: str = Field(min_length=10, max_length=500)
    severity: Literal["high", "medium", "low"]
    evidence: Evidence


class Review(BaseModel):
    """The only acceptable successful final answer for every pattern."""

    verdict: Literal["accept", "revise", "reject"]
    findings: list[Finding] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)


# ------------------------------------------------------------ tool I/O ---

class SearchProposalArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class GetPassageArgs(BaseModel):
    passage_id: str = Field(min_length=1, max_length=32)
