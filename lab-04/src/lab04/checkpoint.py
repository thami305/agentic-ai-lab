"""JSON-file checkpoint persistence for Lab 4.

A CheckpointStore writes one JSON file per run_id after every graph node:

    <run_id>.json = {
        "run_id": run_id,
        "status": "running" | "awaiting_approval" | "finished" | "decided",
        "next_node": <router result or None>,
        "decision": <approval decision or None>,
        "edited": <bool>,
        "updated_at": <epoch seconds>,
        "state": { ...full BriefState... },
    }

Serialization: the BriefState `packet` field goes through
packet.model_dump(), `brief` through brief.model_dump() when present, and
every other field is plain JSON already.

TTL: the store takes an injectable clock (now_fn) so tests can freeze or
travel through time deterministically. load() raises StaleCheckpointError
when now - updated_at > ttl_seconds: the run fails closed instead of
resuming from stale state.

The store also owns the two audit logs that make approval idempotent:
decisions.jsonl (every human decision, appended once) and
side_effects.jsonl (publish side effects keyed by run_id, appended at most
once per run).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lab02.schemas import Packet, ResearchBrief
from lab03.state import BriefState


class CheckpointError(Exception):
    """Base class for checkpoint failures."""


class UnknownRunError(CheckpointError):
    """No checkpoint file exists for this run_id."""


class StaleCheckpointError(CheckpointError):
    """The checkpoint is older than the store TTL: fail closed."""


# BriefState fields that are plain JSON (question/packet/brief handled
# separately because they are typed objects, not primitives).
_STATE_FIELDS = (
    "passages",
    "retrieval_retries",
    "validation_violations",
    "conflict_detail",
    "terminal",
    "terminal_reason",
    "path",
    "tool_calls_made",
    "total_tokens",
)


def state_to_dict(state: BriefState) -> dict:
    d: dict = {"question": state.question}
    d.update({f: getattr(state, f) for f in _STATE_FIELDS})
    d["packet"] = state.packet.model_dump()
    d["brief"] = state.brief.model_dump() if state.brief is not None else None
    return d


def state_from_dict(d: dict) -> BriefState:
    packet = Packet(**d["packet"])
    brief_raw = d.get("brief")
    brief = ResearchBrief(**brief_raw) if brief_raw is not None else None
    kwargs = {f: d[f] for f in _STATE_FIELDS if f in d}
    return BriefState(question=d["question"], packet=packet, brief=brief,
                      **kwargs)


@dataclass
class Checkpoint:
    run_id: str
    status: str  # running | awaiting_approval | finished | decided
    next_node: str | None
    decision: str | None
    edited: bool
    updated_at: float
    state: BriefState


class CheckpointStore:
    """Single-writer JSON file store for run checkpoints and audit logs."""

    def __init__(self, directory: str | Path, ttl_seconds: float = 3600,
                 now_fn: Callable[[], float] = time.time):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.now_fn = now_fn

    # ------------------------------------------------------- checkpoints ---

    def _path(self, run_id: str) -> Path:
        return self.dir / f"{run_id}.json"

    def save(self, run_id: str, state: BriefState, next_node: str | None,
             status: str, decision: str | None = None,
             edited: bool = False) -> dict:
        record = {
            "run_id": run_id,
            "status": status,
            "next_node": next_node,
            "decision": decision,
            "edited": bool(edited),
            "updated_at": self.now_fn(),
            "state": state_to_dict(state),
        }
        self._path(run_id).write_text(json.dumps(record, indent=2),
                                      encoding="utf-8")
        return record

    def load(self, run_id: str) -> Checkpoint:
        path = self._path(run_id)
        if not path.exists():
            raise UnknownRunError(f"no checkpoint for run_id {run_id!r}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        age = self.now_fn() - raw["updated_at"]
        if age > self.ttl_seconds:
            raise StaleCheckpointError(
                f"checkpoint for run_id {run_id!r} is {age:.1f}s old "
                f"(ttl {self.ttl_seconds}s): failing closed")
        return Checkpoint(
            run_id=raw["run_id"],
            status=raw["status"],
            next_node=raw.get("next_node"),
            decision=raw.get("decision"),
            edited=bool(raw.get("edited", False)),
            updated_at=raw["updated_at"],
            state=state_from_dict(raw["state"]),
        )

    # ------------------------------------------------------- audit logs ---

    def log_decision(self, run_id: str, decision: str, edited: bool) -> None:
        """Append one decision record: {run_id, decision, at, edited}."""
        with open(self.dir / "decisions.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "run_id": run_id,
                "decision": decision,
                "at": self.now_fn(),
                "edited": bool(edited),
            }) + "\n")

    def record_side_effect(self, run_id: str, record: dict) -> bool:
        """Append one side-effect record keyed by run_id.

        Returns True when appended, False when a record for this run_id
        already exists: the publish side effect is applied at most once.
        """
        path = self.dir / "side_effects.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and json.loads(line).get("run_id") == run_id:
                    return False
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return True

    def decision_records(self, run_id: str) -> list[dict]:
        return self._records_for("decisions.jsonl", run_id)

    def side_effect_records(self, run_id: str) -> list[dict]:
        return self._records_for("side_effects.jsonl", run_id)

    def _records_for(self, filename: str, run_id: str) -> list[dict]:
        path = self.dir / filename
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("run_id") == run_id:
                out.append(rec)
        return out
