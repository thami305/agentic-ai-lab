"""Lab 10 policy primitives: budgets, namespaces, consent, detectors.

All deterministic. The model proposes; these decide.
"""
from __future__ import annotations

import re
from typing import Any


# ------------------------------------------------------------------ rate ---

class RateLimiter:
    """Cap on tool executions per run. The (n+1)-th call is denied."""

    def __init__(self, max_tool_calls: int) -> None:
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be >= 1")
        self.max_tool_calls = max_tool_calls
        self.count = 0

    def check(self) -> tuple[bool, str]:
        if self.count >= self.max_tool_calls:
            return False, (f"rate_limit_exceeded: {self.count} tool calls "
                           f"already executed (limit {self.max_tool_calls})")
        return True, "ok"

    def record(self) -> None:
        self.count += 1


# ----------------------------------------------------------------- spend ---

class SpendLimiter:
    """Cap on tokens consumed per run."""

    def __init__(self, max_tokens: int) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        self.max_tokens = max_tokens
        self.total = 0

    def add(self, n: int) -> None:
        self.total += max(0, int(n))

    @property
    def exceeded(self) -> bool:
        return self.total > self.max_tokens


# ------------------------------------------------------------- namespace ---

def _find_ns_markers(obj: Any) -> list[str]:
    """Recursively collect every `_ns` namespace marker in tool output."""
    found: list[str] = []
    if isinstance(obj, dict):
        marker = obj.get("_ns")
        if isinstance(marker, str):
            found.append(marker)
        for value in obj.values():
            found.extend(_find_ns_markers(value))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            found.extend(_find_ns_markers(value))
    return found


class NamespaceEnforcer:
    """One run, one client. Data from any other client is denied."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace

    def check_args(self, client_id: str | None) -> tuple[bool, str]:
        if client_id is not None and client_id != self.namespace:
            return False, (f"namespace_violation: run is scoped to "
                           f"'{self.namespace}', tool asked for '{client_id}'")
        return True, "ok"

    def violations_in(self, data: Any) -> list[str]:
        """Namespaces present in tool output that are NOT this run's."""
        return sorted({m for m in _find_ns_markers(data)
                       if m != self.namespace})


# ---------------------------------------------------------------- consent ---

class ConsentStore:
    """Explicit user consent, granted outside the conversation.

    Default-deny: nothing is granted until the user grants it. The model
    cannot grant consent — there is no tool or argument that writes here.
    """

    def __init__(self) -> None:
        self._grants: set[str] = set()

    def grant(self, scope: str) -> None:
        self._grants.add(scope)

    def revoke(self, scope: str) -> None:
        self._grants.discard(scope)

    def granted(self, scope: str) -> bool:
        return scope in self._grants


# --------------------------------------------------------------- detector ---

INSTRUCTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior)\s+instructions",
    r"disregard\s+(your|all|these)\s+instructions",
    r"system\s+override",
    r"\bexecute\s+(the\s+following|this)\b",
    r"run\s+this\s+code",
]


def _strings_in(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(_strings_in(value))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            out.extend(_strings_in(value))
    return out


def looks_like_instruction(data: Any) -> bool:
    """Heuristic: does this tool output contain instruction-like text?

    Used to detect malicious-dependency payloads (attack 4). A hit does not
    execute anything — the loop logs it, treats the output as data only,
    and never follows it.
    """
    for text in _strings_in(data):
        for pattern in INSTRUCTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
    return False
