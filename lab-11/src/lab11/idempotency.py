"""Idempotency keys with a TTL.

A client stamps a request with ``Idempotency-Key``. The first submission runs
the pipeline and records key -> job_id. A repeat submission with the same key
returns the original job without re-running anything — the execution counter
in the tests proves it. Keys expire after ``ttl_s``; an expired key is treated
as brand new and re-executes.
"""
from __future__ import annotations

import time

from .jobs import JobStore


class IdempotencyStore:
    def __init__(self, store: JobStore, ttl_s: float):
        self._store = store
        self._ttl_s = ttl_s

    def lookup(self, key: str, now: float | None = None) -> dict | None:
        """Return the live record for ``key``, or None if missing/expired.

        Expired records are pruned on read, so a stale key transparently
        becomes a new submission.
        """
        now = time.time() if now is None else now
        rec = self._store.idem_get(key)
        if rec is None:
            return None
        if now - rec["created_at"] > self._ttl_s:
            self._store.idem_delete(key)
            return None
        return rec

    def record(self, key: str, job_id: str) -> None:
        self._store.idem_set(key, job_id)
