"""Lab 2 schemas — every boundary crossing is typed and validated.

The brief is the product: factual claims must each carry evidence, and the
deterministic post-validator (validate.py) checks every citation against the
packet. Nothing unvalidated leaves as a brief.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ------------------------------------------------------------- packet ---

class Passage(BaseModel):
    pid: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=2000)


class SourceDoc(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    passages: list[Passage] = Field(min_length=1)


class Packet(BaseModel):
    topic: str
    sources: list[SourceDoc] = Field(min_length=1)


# -------------------------------------------------------------- brief ---

class Evidence(BaseModel):
    """One citation: which source, which passage, and the exact quoted text."""

    source_id: str = Field(min_length=1, max_length=32)
    passage_id: str = Field(min_length=1, max_length=32)
    quote: str = Field(min_length=1, max_length=1000)


class Claim(BaseModel):
    """A factual assertion. Every claim must be supported by evidence —
    unsupported material belongs in open_questions, never in claims."""

    text: str = Field(min_length=10, max_length=500)
    evidence: list[Evidence] = Field(min_length=1)


class ResearchBrief(BaseModel):
    """The only acceptable successful final answer."""

    question: str = Field(min_length=5, max_length=500)
    claims: list[Claim] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(min_length=1)


class Decline(BaseModel):
    """For questions the packet cannot answer."""

    reason: str = Field(min_length=5, max_length=300)


# ----------------------------------------------------------- tool I/O ---

class EmptyArgs(BaseModel):
    """For tools that take no arguments."""


class SearchDocsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class GetPassageArgs(BaseModel):
    source_id: str = Field(min_length=1, max_length=32)
    passage_id: str = Field(min_length=1, max_length=32)


class SearchHit(BaseModel):
    source_id: str
    source_title: str
    passage_id: str
    snippet: str
    score: int


class PassageOut(BaseModel):
    source_id: str
    source_title: str
    passage_id: str
    text: str
