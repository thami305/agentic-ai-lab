"""Durable job state: one JSON file, atomic writes, schema migration.

State file shape (v2)::

    {
      "version": 2,
      "jobs": { "<job_id>": { ...job record... } },
      "idempotency": { "<key>": {"job_id": ..., "created_at": ...} },
      "spend_tokens": 0
    }

v1 (the old shape) looked like::

    {"version": 1,
     "jobs": [{"id": ..., "question": ..., "state": "done|pending|failed",
               "result": {"brief": ...} | null}]}

On load, v1 is migrated to v2 in memory and written back. Crash recovery:
on startup, any job left in ``running`` (the process died mid-job) goes back
to ``queued`` so the worker picks it up — a job is never lost, and because
the pipeline is deterministic, re-running it cannot duplicate an action.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

STATE_VERSION = 2

_V1_STATE_TO_STATUS = {"done": "completed", "pending": "queued", "failed": "failed"}


def _now() -> float:
    return time.time()


def _blank_job(job_id: str, question: str, idempotency_key: str | None) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "question": question,
        "status": "queued",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "attempts": 0,
        "error": None,
        "brief": None,
        "declined": None,
        "decision": None,
        "decided_at": None,
        "tokens_used": 0,
        "idempotency_key": idempotency_key,
    }


def migrate_state_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v1 state file to the v2 shape. Unknown v1 states become queued."""
    jobs: dict[str, dict[str, Any]] = {}
    for old in raw.get("jobs", []):
        job_id = old["id"]
        result = old.get("result") or {}
        jobs[job_id] = {
            "job_id": job_id,
            "question": old.get("question", ""),
            "status": _V1_STATE_TO_STATUS.get(old.get("state"), "queued"),
            "created_at": None,
            "started_at": None,
            "finished_at": None,
            "attempts": 1,
            "error": old.get("error"),
            "brief": result.get("brief"),
            "declined": result.get("decline"),
            "decision": None,
            "decided_at": None,
            "tokens_used": 0,
            "idempotency_key": None,
        }
    return {
        "version": STATE_VERSION,
        "jobs": jobs,
        "idempotency": {},
        "spend_tokens": 0,
    }


def _fresh_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "jobs": {}, "idempotency": {}, "spend_tokens": 0}


class JobStore:
    """Thread-safe JSON-backed job store. All mutations persist atomically."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state = self._load()

    # ------------------------------------------------------------ load ---

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            state = _fresh_state()
            self._write(state)
            return state
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        version = raw.get("version", 1)
        if version == 1:
            state = migrate_state_v1_to_v2(raw)
            self._write(state)  # persist the migrated shape
            return state
        if version != STATE_VERSION:
            raise ValueError(f"unsupported state version: {version}")
        state = _fresh_state()
        state.update(raw)
        return state

    def _write(self, state: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _save(self) -> None:
        self._write(self._state)

    # ------------------------------------------------------------ jobs ---

    def create_job(self, job_id: str, question: str,
                   idempotency_key: str | None) -> dict[str, Any]:
        with self._lock:
            job = _blank_job(job_id, question, idempotency_key)
            self._state["jobs"][job_id] = job
            self._save()
            return dict(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._state["jobs"].get(job_id)
            return dict(job) if job else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._state["jobs"].values())
        jobs.sort(key=lambda j: (j["created_at"] or 0, j["job_id"]))
        return [dict(j) for j in jobs]

    def mark_running(self, job_id: str) -> bool:
        """queued -> running. False if the job is not queued (already handled)."""
        with self._lock:
            job = self._state["jobs"].get(job_id)
            if job is None or job["status"] != "queued":
                return False
            job["status"] = "running"
            job["started_at"] = _now()
            job["attempts"] += 1
            self._save()
            return True

    def finish_job(self, job_id: str, status: str,
                   brief: dict | None = None, declined: dict | None = None,
                   error: str | None = None, tokens_used: int = 0) -> bool:
        """running -> terminal. False if the job is no longer running: a late
        thread (timeout abandon, pre-crash worker) must not clobber the
        recorded outcome."""
        assert status in ("completed", "failed")
        with self._lock:
            job = self._state["jobs"].get(job_id)
            if job is None or job["status"] != "running":
                return False
            job["status"] = status
            job["finished_at"] = _now()
            job["brief"] = brief
            job["declined"] = declined
            job["error"] = error
            job["tokens_used"] = tokens_used
            self._save()
            return True

    def requeue(self, job_id: str) -> bool:
        """failed -> queued, clearing the previous outcome for a retry."""
        with self._lock:
            job = self._state["jobs"].get(job_id)
            if job is None or job["status"] != "failed":
                return False
            job["status"] = "queued"
            job["started_at"] = None
            job["finished_at"] = None
            job["error"] = None
            job["brief"] = None
            job["declined"] = None
            job["tokens_used"] = 0
            self._save()
            return True

    def record_decision(self, job_id: str, decision: str) -> dict[str, Any] | None:
        """Approve/reject a completed job. Returns None unless completed."""
        with self._lock:
            job = self._state["jobs"].get(job_id)
            if job is None or job["status"] != "completed":
                return None
            job["decision"] = decision
            job["decided_at"] = _now()
            self._save()
            return dict(job)

    # ------------------------------------------------------- idempotency ---

    def idem_get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._state["idempotency"].get(key)
            return dict(rec) if rec else None

    def idem_set(self, key: str, job_id: str) -> None:
        with self._lock:
            self._state["idempotency"][key] = {"job_id": job_id, "created_at": _now()}
            self._save()

    def idem_delete(self, key: str) -> None:
        with self._lock:
            self._state["idempotency"].pop(key, None)
            self._save()

    # ------------------------------------------------------------ spend ---

    @property
    def spend_tokens(self) -> int:
        with self._lock:
            return int(self._state.get("spend_tokens", 0))

    def add_spend(self, tokens: int) -> int:
        with self._lock:
            self._state["spend_tokens"] = int(self._state.get("spend_tokens", 0)) + tokens
            self._save()
            return self._state["spend_tokens"]

    # ---------------------------------------------------------- recovery ---

    def recover(self) -> int:
        """Crash recovery: jobs stuck in 'running' go back to 'queued'.
        Returns the number of jobs requeued."""
        with self._lock:
            n = 0
            for job in self._state["jobs"].values():
                if job["status"] == "running":
                    job["status"] = "queued"
                    job["started_at"] = None
                    n += 1
            if n:
                self._save()
            return n
