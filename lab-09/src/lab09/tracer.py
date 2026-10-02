"""Lab 9 tracer: span-level observability WITHOUT touching lab-02/lab-03 source.

The model proposes, deterministic code decides — and the tracer watches.
Instrumentation is purely additive:

- Agent path: the backend is wrapped in a delegating proxy so every
  ``backend.next()`` call becomes a "model" span; every tool ``fn`` is
  wrapped so each execution becomes a "tool" span. The lab02 ``Agent`` is
  constructed with the wrapped pieces — lab02's own files are untouched.
- Graph path: each graph node's ``fn`` is wrapped (a "path" span per node
  visit) and the policy's ``retrieve``/``synthesize`` are wrapped ("tool"
  spans; a failed ``retrieve`` attempt also emits a "retry" span). The graph
  runtime itself already records ``state.path``; the tracer copies it.

A span is a plain dict:
    {span: "model"|"tool"|"retry"|"approval"|"error"|"path",
     name: str, latency_ms: float, tokens: int, ok: bool, detail: str|None}

One JSON trace per case: {"case_id": ..., "spans": [...], "path": [...]}.
Tests use the tracer in-memory; the run_golden CLI writes traces/*.json.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from lab02.tools import ToolDef, ToolRegistry


Span = dict[str, Any]


class Tracer:
    """Collects spans for one run. Not thread-safe; one tracer per run."""

    def __init__(self) -> None:
        self.spans: list[Span] = []
        self.path: list[str] = []

    def record(self, span: str, name: str, latency_ms: float = 0.0,
               tokens: int = 0, ok: bool = True,
               detail: str | None = None) -> None:
        self.spans.append({
            "span": span, "name": name,
            "latency_ms": round(latency_ms, 3), "tokens": int(tokens),
            "ok": ok, "detail": detail,
        })

    def set_path(self, path: list[str]) -> None:
        self.path = list(path)

    def spans_of(self, kind: str) -> list[Span]:
        return [s for s in self.spans if s["span"] == kind]

    def to_dict(self, case_id: str) -> dict[str, Any]:
        return {"case_id": case_id, "spans": list(self.spans),
                "path": list(self.path)}


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


# ------------------------------------------------- agent instrumentation ---

class TracedBackend:
    """Delegating proxy: start_run/observe_tool_results pass through, every
    next() is recorded as a "model" span. Satisfies the ModelBackend protocol
    structurally, so lab02.Agent accepts it unchanged."""

    def __init__(self, backend: Any, tracer: Tracer) -> None:
        self._backend = backend
        self._tracer = tracer
        self.backend_name = type(backend).__name__

    def start_run(self, system: str, user_request: str,
                  tools: list[dict[str, Any]]) -> None:
        self._backend.start_run(system, user_request, tools)

    def next(self) -> Any:
        t0 = _now_ms()
        ok, tokens = True, 0
        try:
            resp = self._backend.next()
            usage = getattr(resp, "usage", {}) or {}
            tokens = int(usage.get("prompt_tokens", 0)
                         + usage.get("completion_tokens", 0))
            return resp
        except Exception as e:
            ok = False
            raise
        finally:
            self._tracer.record("model", self.backend_name,
                                latency_ms=_now_ms() - t0, tokens=tokens,
                                ok=ok)

    def observe_tool_results(self, results: list[Any]) -> None:
        self._backend.observe_tool_results(results)


def traced_tool_registry(registry: ToolRegistry, tracer: Tracer) -> ToolRegistry:
    """Rebuild the registry with the same ToolDefs but wrapped fns: each tool
    execution becomes a "tool" span; a raised exception becomes an "error"
    span as well (the agent converts it to a failed ToolResult)."""
    new_reg = ToolRegistry()
    for tool in registry.all():
        new_reg.register(ToolDef(
            name=tool.name,
            description=tool.description,
            args_model=tool.args_model,
            fn=_wrap_tool_fn(tool.name, tool.fn, tracer),
            timeout_s=tool.timeout_s,
            max_retries=tool.max_retries,
        ))
    return new_reg


def _wrap_tool_fn(name: str, fn: Callable[..., Any],
                  tracer: Tracer) -> Callable[..., Any]:
    def wrapped(**kwargs: Any) -> Any:
        t0 = _now_ms()
        ok = True
        try:
            return fn(**kwargs)
        except Exception as e:
            ok = False
            tracer.record("error", name, latency_ms=_now_ms() - t0,
                          detail=f"{type(e).__name__}: {e}")
            raise
        finally:
            tracer.record("tool", name, latency_ms=_now_ms() - t0, ok=ok)
    wrapped.__name__ = f"traced_{name}"
    return wrapped


# ------------------------------------------------- graph instrumentation ---

def instrument_graph(graph: Any, tracer: Tracer) -> Any:
    """Wrap every node fn so each node visit is a "path" span. Mutates only
    the in-memory Graph built for this run — lab03's source is untouched."""
    for node in graph.nodes.values():
        node.fn = _wrap_node_fn(node.name, node.fn, tracer)
    return graph


def _wrap_node_fn(name: str, fn: Callable[[Any], None],
                  tracer: Tracer) -> Callable[[Any], None]:
    def wrapped(state: Any) -> None:
        t0 = _now_ms()
        ok = True
        try:
            fn(state)
        except Exception:
            ok = False
            raise
        finally:
            tracer.record("path", name, latency_ms=_now_ms() - t0, ok=ok)
    wrapped.__name__ = f"traced_node_{name}"
    return wrapped


def instrument_policy(policy: Any, tracer: Tracer) -> Any:
    """Wrap policy.retrieve / policy.synthesize as "tool" spans; each failed
    retrieve attempt additionally emits a "retry" span. The policy instance
    is lab09-owned (created per case in the runner), so attribute wrapping
    is contained."""
    orig_retrieve = policy.retrieve
    orig_synthesize = policy.synthesize

    def retrieve(state: Any) -> Any:
        t0 = _now_ms()
        ok = True
        try:
            return orig_retrieve(state)
        except Exception as e:
            ok = False
            tracer.record("retry", "retrieve", latency_ms=_now_ms() - t0,
                          ok=False, detail=f"{type(e).__name__}: {e}")
            raise
        finally:
            tracer.record("tool", "retrieve", latency_ms=_now_ms() - t0,
                          ok=ok)

    def synthesize(state: Any) -> Any:
        t0 = _now_ms()
        ok = True
        try:
            return orig_synthesize(state)
        except Exception as e:
            ok = False
            tracer.record("error", "synthesize", latency_ms=_now_ms() - t0,
                          detail=f"{type(e).__name__}: {e}")
            raise
        finally:
            tracer.record("tool", "synthesize", latency_ms=_now_ms() - t0,
                          ok=ok)

    policy.retrieve = retrieve
    policy.synthesize = synthesize
    return policy
