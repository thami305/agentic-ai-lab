"""Structured JSON-lines logging with secret redaction.

Every request and job lifecycle event is one JSON line. Before anything is
written, values are scrubbed:

- header/field names matching bearer, token, api-key, secret, password, ...
  have their whole value replaced;
- string values that look like issued keys (``sk-...``) are replaced wherever
  they appear, including inside free text.

The rule is deliberately broad: a log line must never be the place a
credential leaks from.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_NAME = re.compile(
    r"(?i)(authorization|bearer|api[_-]?key|secret|password|passwd|token|session|cookie)"
)
_KEYLIKE_VALUE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


def _redact_value(name: str | None, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(None, v) for v in value]
    if isinstance(value, str):
        if name is not None and _SENSITIVE_NAME.search(name):
            return REDACTED
        redacted, n = _KEYLIKE_VALUE.subn(REDACTED, value)
        if n:
            return redacted
        return value
    return value


def redact(obj: Any) -> Any:
    """Return a copy of ``obj`` with secrets scrubbed."""
    return _redact_value(None, obj)


class JsonLogger:
    """Append-only JSON-lines logger. Thread-safe."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event: str, **fields: Any) -> None:
        record = {"ts": time.time(), "event": event, **redact(fields)}
        line = json.dumps(record, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
