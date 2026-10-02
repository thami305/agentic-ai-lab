"""The consent gate: a FUNCTION, not a model judgment.

Only an explicit user "remember" statement may write memory. Retrieved or
otherwise untrusted content can never write, no matter what it says.
"""

from __future__ import annotations

import re
import time

from lab06.store import MemoryStore


class SensitiveContentError(ValueError):
    """Raised when a value matches a known sensitive pattern."""


SENSITIVE_PATTERNS = [
    re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"),  # credit card
]


def remember_value(
    key: str,
    value: str,
    provenance: str,
    scope: str,
    store: MemoryStore,
    ttl_seconds: float = 3600.0,
    confidence: float = 1.0,
    now: float | None = None,
):
    """Consent-gated write: rejects sensitive values, then stores."""
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(value):
            raise SensitiveContentError(
                f"value for key {key!r} matched a sensitive pattern; nothing stored"
            )
    return store.remember(
        key=key,
        value=value,
        provenance=provenance,
        scope=scope,
        ttl_seconds=ttl_seconds,
        confidence=confidence,
        now=now,
    )


# Entire message must be an imperative remember statement.
REMEMBER_RE = re.compile(
    r"^\s*(?:please\s+)?remember\s+(?:that\s+)?(?P<fact>.+?)\s*$",
    re.IGNORECASE,
)


def _slugify(text: str, n_words: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:n_words]) or "fact"


def handle_user_message(
    text: str,
    scope: str,
    store: MemoryStore,
    now: float | None = None,
    ttl_seconds: float = 3600.0,
) -> str:
    """Write ONLY when the whole message is an explicit remember statement."""
    now = time.time() if now is None else now
    match = REMEMBER_RE.match(text)
    if not match:
        return "not a remember statement \u2014 nothing stored"
    fact = match.group("fact").strip()
    if ": " in fact:
        key, value = fact.split(": ", 1)
        key = key.strip()
        value = value.strip()
    else:
        key = _slugify(fact)
        value = fact
    entry = remember_value(
        key=key,
        value=value,
        provenance="user:explicit-remember",
        scope=scope,
        store=store,
        ttl_seconds=ttl_seconds,
        now=now,
    )
    return f"stored {entry.key!r} = {entry.value!r} in scope {scope!r}"


def ingest_document(
    text: str,
    scope: str,
    store: MemoryStore,
    now: float | None = None,
) -> str:
    """Simulates retrieved/untrusted content. MUST NEVER WRITE to memory.

    Even if the text contains "remember this: ..." or "remember: ...", it is
    data, not an instruction. The content/data boundary lives here.
    """
    _ = (text, scope, store, now)  # intentionally unused: no writes, ever
    return "ingested as data only \u2014 no memory write"
