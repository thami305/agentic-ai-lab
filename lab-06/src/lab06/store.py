"""JSON-file memory store with namespaces, expiry (decay), and tombstones."""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, Field


class ProvenanceEntry(BaseModel):
    source: str
    at: float


class HistoryEntry(BaseModel):
    value: str
    provenance: list[ProvenanceEntry]
    timestamp: float


class Entry(BaseModel):
    key: str
    value: str
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    timestamp: float
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    scope: str
    expiry: float
    history: list[HistoryEntry] = Field(default_factory=list)
    tombstoned: bool = False
    deleted_at: float | None = None


class MemoryStore:
    """Tiny JSON-file memory store.

    File format: JSON object mapping key -> entry dict.
    All methods take an injectable ``now`` (epoch float, default time.time)
    so TTL/expiry behavior is deterministic in tests.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict:
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    @staticmethod
    def _live(entry: Entry, now: float) -> bool:
        return (not entry.tombstoned) and (now < entry.expiry)

    def remember(
        self,
        key: str,
        value: str,
        provenance: str,
        scope: str,
        ttl_seconds: float,
        confidence: float = 1.0,
        now: float | None = None,
    ) -> Entry:
        now = time.time() if now is None else now
        prov = ProvenanceEntry(source=provenance, at=now)
        data = self._read()
        existing = data.get(key)
        entry: Entry | None = Entry(**existing) if existing is not None else None

        if entry is not None and not entry.tombstoned and now < entry.expiry:
            # Contradictory update: newer wins, but log both provenances.
            entry.history.append(
                HistoryEntry(
                    value=entry.value,
                    provenance=list(entry.provenance),
                    timestamp=entry.timestamp,
                )
            )
            entry.value = value
            entry.provenance.append(prov)
            entry.timestamp = now
            entry.expiry = now + ttl_seconds
            entry.confidence = confidence
            entry.scope = scope
        else:
            if entry is not None and entry.tombstoned:
                # Re-remember after delete: clear tombstone, keep history.
                history = entry.history
                prov_log = list(entry.provenance)
            else:
                history = []
                prov_log = []
            prov_log.append(prov)
            entry = Entry(
                key=key,
                value=value,
                provenance=prov_log,
                timestamp=now,
                confidence=confidence,
                scope=scope,
                expiry=now + ttl_seconds,
                history=history,
                tombstoned=False,
                deleted_at=None,
            )
        data[key] = entry.model_dump()
        self._write(data)
        return entry

    def get(self, key: str, scope: str, now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        data = self._read()
        raw = data.get(key)
        if raw is None:
            return None
        entry = Entry(**raw)
        if entry.scope != scope:
            return None
        if not self._live(entry, now):
            return None
        return entry.value

    def get_entry(self, key: str, now: float | None = None) -> Entry | None:
        """Raw accessor used by tests/debug (not a scoped read)."""
        data = self._read()
        raw = data.get(key)
        return Entry(**raw) if raw is not None else None

    def delete(self, key: str, scope: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        data = self._read()
        raw = data.get(key)
        if raw is None:
            return False
        entry = Entry(**raw)
        if entry.scope != scope or entry.tombstoned:
            return False
        tombstone = Entry(
            key=entry.key,
            value="",
            provenance=entry.provenance,  # provenance WITHOUT values
            timestamp=entry.timestamp,
            confidence=entry.confidence,
            scope=entry.scope,
            expiry=entry.expiry,
            history=[],  # history values scrubbed
            tombstoned=True,
            deleted_at=now,
        )
        data[key] = tombstone.model_dump()
        self._write(data)
        return True

    def verify_absent(self, key: str, value: str) -> bool:
        """Read the raw file bytes; True iff ``value`` appears nowhere."""
        raw = self.path.read_bytes().decode("utf-8", errors="replace")
        return value not in raw

    def list_keys(self, scope: str, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        data = self._read()
        out = []
        for key, raw in data.items():
            entry = Entry(**raw)
            if entry.scope == scope and self._live(entry, now):
                out.append(key)
        return sorted(out)
