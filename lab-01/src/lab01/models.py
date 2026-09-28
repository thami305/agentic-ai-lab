"""Model backends for Lab 1.

The agent loop speaks one internal protocol (ModelResponse); backends translate.
- ScriptedStub: deterministic replay. Powers all 20 acceptance tests.
- OpenAIBackend / AnthropicBackend: real providers. Bring a key + set LAB_MODEL.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import ValidationError

from .schemas import Decline, Recommendation

if TYPE_CHECKING:  # avoid a runtime import cycle with agent.py
    from .agent import ToolResult


class ModelError(RuntimeError):
    """The model (not a tool) failed: transport error or unparseable output."""


@dataclass
class ToolCallItem:
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelResponse:
    kind: Literal["tool_calls", "final", "decline"]
    tool_calls: list[ToolCallItem] = field(default_factory=list)
    final: Any = None   # Recommendation | Decline | raw dict (agent validates)
    decline: Any = None  # Decline | raw dict (agent validates)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})


class ModelBackend(Protocol):
    def start_run(self, system: str, user_request: str, tools: list[dict[str, Any]]) -> None: ...
    def next(self) -> ModelResponse: ...
    def observe_tool_results(self, results: list["ToolResult"]) -> None: ...


# ---------------------------------------------------------------- stub ---

class ScriptedStub(ModelBackend):
    """Replays a fixed script of responses. The same script always produces
    the same run, which is what makes the acceptance tests deterministic."""

    def __init__(self, script: list[ModelResponse],
                 usage_per_turn: dict[str, int] | None = None):
        self._script = list(script)
        self.usage_per_turn = usage_per_turn or {"prompt_tokens": 600, "completion_tokens": 120}
        self.turns_taken = 0

    def start_run(self, system: str, user_request: str, tools: list[dict[str, Any]]) -> None:
        self.turns_taken = 0

    def next(self) -> ModelResponse:
        self.turns_taken += 1
        if not self._script:
            raise ModelError("stub script exhausted — the model asked for another turn")
        resp = self._script.pop(0)
        return ModelResponse(kind=resp.kind, tool_calls=list(resp.tool_calls),
                             final=resp.final, decline=resp.decline,
                             usage=dict(self.usage_per_turn))

    def observe_tool_results(self, results: list["ToolResult"]) -> None:
        pass


def tc(name: str, arguments: dict[str, Any] | None = None) -> ToolCallItem:
    return ToolCallItem(name=name, arguments=arguments or {})


def calls(*items: ToolCallItem) -> ModelResponse:
    return ModelResponse(kind="tool_calls", tool_calls=list(items))


def final_rec(**kwargs: Any) -> ModelResponse:
    return ModelResponse(kind="final", final=Recommendation(**kwargs))


def final_raw(data: dict[str, Any]) -> ModelResponse:
    return ModelResponse(kind="final", final=data)


def decline(reason: str) -> ModelResponse:
    return ModelResponse(kind="decline", decline=Decline(reason=reason))


# ------------------------------------------------------------- OpenAI ---

class OpenAIBackend(ModelBackend):
    """Real model via the OpenAI SDK. Requires `pip install openai`,
    OPENAI_API_KEY set, and LAB_MODEL set to a current model id."""

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("LAB_MODEL")
        if not self.model:
            raise ModelError("Set the LAB_MODEL env var to the model id you want to use.")
        self._messages: list[dict[str, Any]] = []
        self._pending: list[Any] = []

    def _client(self):  # lazy: import only when actually used
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ModelError("The 'openai' package is not installed (pip install openai).") from e
        if not os.environ.get("OPENAI_API_KEY"):
            raise ModelError("OPENAI_API_KEY is not set.")
        return OpenAI()

    def start_run(self, system: str, user_request: str, tools: list[dict[str, Any]]) -> None:
        self._client()  # fail fast on missing key/package
        self._tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["parameters"]}} for t in tools]
        self._messages = [{"role": "system", "content": system},
                          {"role": "user", "content": user_request}]
        self._pending = []

    def next(self) -> ModelResponse:
        resp = self._client().chat.completions.create(
            model=self.model, messages=self._messages,
            tools=self._tools, tool_choice="auto")
        msg = resp.choices[0].message
        usage = {"prompt_tokens": (resp.usage.prompt_tokens if resp.usage else 0),
                 "completion_tokens": (resp.usage.completion_tokens if resp.usage else 0)}
        if msg.tool_calls:
            self._pending = list(msg.tool_calls)
            self._messages.append(msg.model_dump(exclude_none=True))
            return ModelResponse(
                kind="tool_calls", usage=usage,
                tool_calls=[ToolCallItem(name=c.function.name,
                                         arguments=json.loads(c.function.arguments or "{}"))
                            for c in msg.tool_calls])
        content = msg.content or ""
        self._messages.append({"role": "assistant", "content": content})
        for cls, kind in ((Recommendation, "final"), (Decline, "decline")):
            try:
                return ModelResponse(kind=kind, **{kind: cls.model_validate_json(content)}, usage=usage)  # type: ignore[arg-type]
            except ValidationError:
                continue
        raise ModelError("Model returned text that matches neither Recommendation nor Decline schema.")

    def observe_tool_results(self, results: list["ToolResult"]) -> None:
        for native, res in zip(self._pending, results):
            payload = {"ok": res.ok, "data": res.data, "error": res.error,
                       "cached": res.cached}
            self._messages.append({"role": "tool", "tool_call_id": native.id,
                                   "content": "[UNTRUSTED TOOL DATA]\n" + json.dumps(payload)})
        self._pending = []


# ---------------------------------------------------------- Anthropic ---

class AnthropicBackend(ModelBackend):
    """Real model via the Anthropic SDK. Requires `pip install anthropic`,
    ANTHROPIC_API_KEY set, and LAB_MODEL set to a current model id."""

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("LAB_MODEL")
        if not self.model:
            raise ModelError("Set the LAB_MODEL env var to the model id you want to use.")
        self._messages: list[dict[str, Any]] = []
        self._pending: list[Any] = []

    def _client(self):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ModelError("The 'anthropic' package is not installed (pip install anthropic).") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ModelError("ANTHROPIC_API_KEY is not set.")
        return Anthropic()

    def start_run(self, system: str, user_request: str, tools: list[dict[str, Any]]) -> None:
        self._client()  # fail fast
        self._system = system
        self._tools = [{"name": t["name"], "description": t["description"],
                        "input_schema": t["parameters"]} for t in tools]
        self._messages = [{"role": "user", "content": user_request}]
        self._pending = []

    def next(self) -> ModelResponse:
        resp = self._client().messages.create(
            model=self.model, system=self._system, messages=self._messages,
            tools=self._tools, max_tokens=1024)
        usage = {"prompt_tokens": resp.usage.input_tokens,
                 "completion_tokens": resp.usage.output_tokens}
        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        text = "".join(getattr(b, "text", "") for b in resp.content
                       if getattr(b, "type", "") == "text")
        if tool_uses:
            self._pending = tool_uses
            self._messages.append({"role": "assistant", "content": resp.content})
            return ModelResponse(
                kind="tool_calls", usage=usage,
                tool_calls=[ToolCallItem(name=b.name, arguments=dict(b.input or {}))
                            for b in tool_uses])
        self._messages.append({"role": "assistant", "content": text})
        for cls, kind in ((Recommendation, "final"), (Decline, "decline")):
            try:
                return ModelResponse(kind=kind, **{kind: cls.model_validate_json(text)}, usage=usage)  # type: ignore[arg-type]
            except ValidationError:
                continue
        raise ModelError("Model returned text that matches neither Recommendation nor Decline schema.")

    def observe_tool_results(self, results: list["ToolResult"]) -> None:
        tool_results = [{"type": "tool_result", "tool_use_id": b.id,
                         "content": "[UNTRUSTED TOOL DATA]\n" + json.dumps(
                             {"ok": r.ok, "data": r.data, "error": r.error, "cached": r.cached})}
                        for b, r in zip(self._pending, results)]
        self._messages.append({"role": "user", "content": tool_results})
        self._pending = []
