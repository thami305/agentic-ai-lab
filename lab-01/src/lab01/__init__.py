"""Lab 1: deterministic tool-using assistant."""
from .agent import Agent, AgentConfig, RunResult, SYSTEM_PROMPT, ToolResult
from .db import seed
from .models import (AnthropicBackend, ModelBackend, ModelError, ModelResponse,
                     OpenAIBackend, ScriptedStub, ToolCallItem, calls, decline,
                     final_raw, final_rec, tc)
from .schemas import (CalculateMetricArgs, Confidence, Decline, EmptyArgs,
                      GetClientArgs, ListDealsArgs, MetricName, Recommendation,
                      RecommendationKind)
from .tools import ToolDef, ToolRegistry, build_registry

__all__ = [
    "Agent", "AgentConfig", "RunResult", "SYSTEM_PROMPT", "ToolResult",
    "seed", "AnthropicBackend", "ModelBackend", "ModelError", "ModelResponse",
    "OpenAIBackend", "ScriptedStub", "ToolCallItem", "calls", "decline",
    "final_raw", "final_rec", "tc", "CalculateMetricArgs", "Confidence",
    "Decline", "EmptyArgs", "GetClientArgs", "ListDealsArgs", "MetricName",
    "Recommendation", "RecommendationKind", "ToolDef", "ToolRegistry",
    "build_registry",
]
