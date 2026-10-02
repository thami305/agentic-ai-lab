"""Lab 06: Memory with consent and decay."""

from lab06.gate import (
    SensitiveContentError,
    handle_user_message,
    ingest_document,
)
from lab06.store import Entry, MemoryStore

__all__ = [
    "Entry",
    "MemoryStore",
    "SensitiveContentError",
    "handle_user_message",
    "ingest_document",
]
