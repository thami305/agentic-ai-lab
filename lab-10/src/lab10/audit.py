"""Lab 10 audit log — append-only, hash-chained, tamper-evident.

Every allow/deny decision the hardened loop makes lands here with a reason.
Each entry commits to the previous entry's hash, so deleting or editing any
line breaks the chain. There is no public API to mutate or delete entries;
`entries()` hands out copies.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _hash_entry(entry: dict[str, Any]) -> str:
    blob = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only JSON-lines log with a hash chain.

    Pass `path` to persist each entry as it is appended (CLI runs). Omit it
    for a pure in-memory log (tests).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = []
        if self._path is not None and self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._entries.append(json.loads(line))

    def append(self, event: str, *, reason: str | None = None,
               tool: str | None = None, run_id: str | None = None,
               **fields: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "seq": len(self._entries),
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "event": event,
            "reason": reason,
            "tool": tool,
            **fields,
        }
        entry["prev_hash"] = (self._entries[-1]["hash"]
                              if self._entries else "GENESIS")
        entry["hash"] = _hash_entry(entry)
        self._entries.append(entry)
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
        return dict(entry)

    def entries(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self._entries]

    def denials(self) -> list[dict[str, Any]]:
        return [e for e in self.entries() if e["event"] == "denied"]

    def tail(self, n: int = 5) -> list[dict[str, Any]]:
        return self.entries()[-n:]

    def verify_chain(self) -> tuple[bool, str]:
        """Recompute the chain. Returns (ok, message)."""
        prev = "GENESIS"
        for i, entry in enumerate(self._entries):
            if entry.get("seq") != i:
                return False, f"seq break at index {i}"
            if entry.get("prev_hash") != prev:
                return False, f"prev_hash mismatch at seq {i}"
            recomputed = _hash_entry(
                {k: v for k, v in entry.items() if k != "hash"})
            if entry.get("hash") != recomputed:
                return False, f"hash mismatch at seq {i}"
            prev = entry["hash"]
        return True, f"chain ok: {len(self._entries)} entries"
