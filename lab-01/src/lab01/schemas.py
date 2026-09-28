"""Lab 1 schemas — every boundary crossing is typed and validated.

The agent loop, the tool registry, and the final answer all speak Pydantic.
Nothing unvalidated reaches a tool, and nothing unvalidated leaves as a
recommendation.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MetricName = Literal["weighted_pipeline", "win_rate", "avg_deal_size", "total_pipeline"]
RecommendationKind = Literal["expand", "hold", "review", "escalate"]
Confidence = Literal["low", "medium", "high"]


class EmptyArgs(BaseModel):
    """For tools that take no arguments."""


class GetClientArgs(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)


class ListDealsArgs(BaseModel):
    client_id: str | None = Field(default=None, max_length=64)
    stage: str | None = Field(default=None, max_length=32)
    limit: int = Field(default=50, ge=1, le=200)


class CalculateMetricArgs(BaseModel):
    metric: MetricName
    client_id: str | None = Field(default=None, max_length=64)
    stage: str | None = Field(default=None, max_length=32)


class Recommendation(BaseModel):
    """The only acceptable successful final answer."""

    client_id: str
    metric_name: str
    metric_value: float
    recommendation: RecommendationKind
    rationale: str = Field(min_length=10, max_length=500)
    confidence: Confidence
    data_sources: list[str] = Field(min_length=1)


class Decline(BaseModel):
    """For requests outside the agent's scope."""

    reason: str = Field(min_length=5, max_length=300)
