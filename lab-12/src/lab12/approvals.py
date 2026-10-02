"""Approval queue: the human gate in front of every state-changing action.

Rules:
  1. Actions are queued by the copilot (or a human operator) — never executed
     at queue time.
  2. approve() executes exactly once, and only from state 'pending'.
  3. reject() marks the entry rejected; it can never be executed afterwards.
  4. The action callable is resolved dynamically from the actions module at
     approve() time, so tests can spy on it with monkeypatch.

The queue persists to JSON so a crash between queueing and approval loses
nothing, and an audit trail survives the process.
"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from . import actions


class QueueEntry(BaseModel):
    id: str
    case_id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="pending")  # pending | approved | rejected
    executed: bool = False
    result: dict[str, Any] | None = None


class ApprovalQueue:
    def __init__(self, path: str):
        self.path = path
        self._entries: dict[str, QueueEntry] = {}
        if os.path.exists(path):
            self._load()

    # ------------------------------------------------------------- I/O ---

    def _load(self) -> None:
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        self._entries = {e["id"]: QueueEntry.model_validate(e)
                         for e in raw.get("entries", [])}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"entries": [e.model_dump() for e in
                                    self._entries.values()]},
                      f, indent=2)

    # ---------------------------------------------------------- queueing ---

    def queue(self, case_id: str, action: str, payload: dict[str, Any]) -> QueueEntry:
        if not hasattr(actions, action):
            raise ValueError(f"unknown action '{action}' — not in the action registry")
        entry_id = f"q{len(self._entries) + 1:03d}"
        entry = QueueEntry(id=entry_id, case_id=case_id, action=action,
                           payload=dict(payload))
        self._entries[entry_id] = entry
        self._save()
        return entry

    def pending(self) -> list[QueueEntry]:
        return [e for e in self._entries.values() if e.status == "pending"]

    def get(self, entry_id: str) -> QueueEntry:
        return self._entries[entry_id]

    # ---------------------------------------------------------- approval ---

    def approve(self, entry_id: str) -> dict[str, Any]:
        """Execute exactly once. Only from 'pending'. Anything else raises
        and the action never runs."""
        entry = self._entries[entry_id]
        if entry.status != "pending" or entry.executed:
            raise RuntimeError(
                f"entry {entry_id} is '{entry.status}' "
                f"(executed={entry.executed}) — refusing to run twice")
        fn = getattr(actions, entry.action)  # dynamic: tests can spy on this
        result = fn(**entry.payload)
        entry.executed = True
        entry.status = "approved"
        entry.result = result
        self._save()
        return result

    def reject(self, entry_id: str, reason: str = "") -> QueueEntry:
        entry = self._entries[entry_id]
        if entry.status != "pending":
            raise RuntimeError(f"entry {entry_id} is '{entry.status}' — nothing to reject")
        entry.status = "rejected"
        self._save()
        return entry
