"""HTTP service: routes, auth, budgets, the dispatcher, and lifecycle.

``App`` owns everything: the durable ``JobStore``, the idempotency store, the
JSON-lines logger, the kill flag, the concurrency semaphore, and the
dispatcher thread that feeds queued jobs to worker threads.

``make_server`` builds a ``ThreadingHTTPServer`` on an ephemeral port (tests)
or a fixed one (the CLI). Handlers reach the app via ``server.app``.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import types
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from lab02.models import OracleStub
from lab02.packet import load_packet

from .auth import check_bearer
from .config import ServiceConfig
from .idempotency import IdempotencyStore
from .jobs import JobStore
from .limits import check_budgets
from .log import JsonLogger
from .ui import REVIEW_UI
from .worker import Pipeline, default_registry_factory


class BriefRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "question": job["question"],
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "attempts": job["attempts"],
        "error": job["error"],
        "brief": job["brief"],
        "declined": job["declined"],
        "decision": job["decision"],
        "decided_at": job["decided_at"],
        "tokens_used": job["tokens_used"],
    }


class App:
    def __init__(
        self,
        data_dir: str | Path,
        config: ServiceConfig | None = None,
        policy_factory: Callable[[Any], Any] | None = None,
        registry_factory: Callable[[Any], Any] | None = None,
    ):
        self.config = config or ServiceConfig()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.store = JobStore(self.data_dir / "jobs.json")
        self.idem = IdempotencyStore(self.store, self.config.idempotency_ttl_s)
        self.logger = JsonLogger(self.data_dir / "server.log.jsonl")

        self.kill_event = threading.Event()
        self.stopped = threading.Event()
        self.slots = threading.Semaphore(self.config.concurrency_limit)
        # Job ids whose concurrency slot is currently held by this process.
        # A fresh boot holds no slots, so recovered jobs acquire in the
        # dispatcher instead of double-counting a slot from before the crash.
        self._slots_held: set[str] = set()
        self._slots_lock = threading.Lock()
        self.executions = 0  # pipeline runs since boot; idempotency proof
        self.started_at = time.monotonic()

        self.packet = load_packet(self.config.packet_path or None)
        self.policy_factory = policy_factory or (lambda ctx: OracleStub())
        self.registry_factory = registry_factory or default_registry_factory
        self.ctx = types.SimpleNamespace(
            kill_event=self.kill_event, stopped=self.stopped, app=self)
        self.pipeline = Pipeline(self)

        self._queue: queue.Queue[str] = queue.Queue()
        self._dispatcher = threading.Thread(target=self._dispatch_loop,
                                            daemon=True, name="lab11-dispatch")

    # ---------------------------------------------------------- lifecycle ---

    def start(self) -> None:
        recovered = self.store.recover()
        # Re-enqueue everything still queued (including crash-recovered jobs);
        # the in-memory queue does not survive a restart, the store does.
        for job in self.store.list_jobs():
            if job["status"] == "queued":
                self._queue.put(job["job_id"])
        self.logger.log("server_started", recovered_jobs=recovered,
                        config=self.config.model_dump())
        self._dispatcher.start()

    def stop(self) -> None:
        self.stopped.set()
        self.logger.log("server_stopped")

    # ------------------------------------------------- slot bookkeeping ---

    def _release_slot(self, job_id: str) -> None:
        with self._slots_lock:
            if job_id in self._slots_held:
                self._slots_held.discard(job_id)
                self.slots.release()

    # --------------------------------------------------------- dispatcher ---

    def _dispatch_loop(self) -> None:
        while not self.stopped.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.kill_event.is_set():
                # Never start new work after the kill.
                self.store.finish_job(job_id, "failed",
                                      error="aborted: kill switch engaged")
                self._release_slot(job_id)
                self.logger.log("job_failed", job_id=job_id,
                                error="aborted: kill switch engaged (queued)")
                continue
            with self._slots_lock:
                held = job_id in self._slots_held
            if not held:
                # Recovered job: no slot was acquired for it in this process.
                # Block here (not at submit) so queue_depth honestly reports
                # jobs waiting for a worker.
                self.slots.acquire()
                with self._slots_lock:
                    self._slots_held.add(job_id)
            if not self.store.mark_running(job_id):
                self._release_slot(job_id)  # already handled; don't leak
                continue
            self.logger.log("job_started", job_id=job_id)
            threading.Thread(target=self._worker_entry, args=(job_id,),
                             daemon=True, name=f"lab11-worker-{job_id[:8]}").start()

    def _worker_entry(self, job_id: str) -> None:
        try:
            self.pipeline.run_job(job_id)
        finally:
            self._release_slot(job_id)

    # ------------------------------------------------------------ submit ---

    def submit(self, job_id: str, question: str,
               idempotency_key: str | None) -> tuple[str, dict[str, Any]]:
        """Enqueue a brief job. Returns (http_status, body).

        The caller must already hold a concurrency slot for ``job_id``
        (acquired via ``try_acquire_slot``); the worker releases it.
        """
        self.store.create_job(job_id, question, idempotency_key)
        if idempotency_key:
            self.idem.record(idempotency_key, job_id)
        self._queue.put(job_id)
        self.logger.log("job_submitted", job_id=job_id,
                        idempotency_key=idempotency_key)
        return "202", {"job_id": job_id, "status": "queued"}

    def try_acquire_slot(self, job_id: str) -> bool:
        """Non-blocking slot acquire for a new submission. False if full."""
        if not self.slots.acquire(blocking=False):
            return False
        with self._slots_lock:
            self._slots_held.add(job_id)
        return True

    def queue_depth(self) -> int:
        return self._queue.qsize()

    def job_counts(self) -> dict[str, int]:
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        for job in self.store.list_jobs():
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        return counts


# ------------------------------------------------------------------ http ---

class Handler(BaseHTTPRequestHandler):
    server_version = "Lab11/1.0"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    # -- helpers --

    def _send_json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code: int, html: str) -> None:
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> tuple[Any | None, str | None]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None, None
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as e:
            return None, f"invalid JSON: {e}"

    def _authed(self) -> bool:
        return check_bearer(self.headers.get("Authorization"),
                            self.app.config.token)

    def _log_request(self, status: int, **extra: Any) -> None:
        self.app.logger.log(
            "request", method=self.command, path=self.path.split("?", 1)[0],
            status=status, headers=dict(self.headers), **extra)

    # -- routing --

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            html = REVIEW_UI.replace("__TOKEN__", self.app.config.token)
            self._send_html(200, html)
            self._log_request(200)
        elif path == "/healthz":
            app = self.app
            self._send_json(200, {
                "status": "ok",
                "killed": app.kill_event.is_set(),
                "uptime_s": round(time.monotonic() - app.started_at, 3),
                "queue_depth": app.queue_depth(),
                "spend_tokens": app.store.spend_tokens,
                "token_budget": app.config.global_token_budget,
                "jobs": app.job_counts(),
            })
            self._log_request(200)
        elif path == "/v1/briefs":
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return self._log_request(401)
            jobs = [_public_job(j) for j in self.app.store.list_jobs()]
            self._send_json(200, {"jobs": jobs})
            self._log_request(200)
        elif path.startswith("/v1/briefs/"):
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return self._log_request(401)
            job_id = path[len("/v1/briefs/"):]
            job = self.app.store.get_job(job_id)
            if job is None or "/" in job_id:
                self._send_json(404, {"error": "unknown job"})
                return self._log_request(404)
            self._send_json(200, _public_job(job))
            self._log_request(200)
        else:
            self._send_json(404, {"error": "not found"})
            self._log_request(404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/admin/kill":
            if not self._authed():
                self._send_json(401, {"error": "unauthorized"})
                return self._log_request(401)
            self.app.kill_event.set()
            self.app.logger.log("kill_switch_engaged")
            self._send_json(200, {"killed": True})
            self._log_request(200)
        elif path == "/v1/briefs":
            self._handle_submit()
        elif path.startswith("/v1/briefs/"):
            rest = path[len("/v1/briefs/"):]
            if "/" in rest:
                job_id, _, action = rest.partition("/")
                if action in ("retry", "approve", "reject"):
                    if not self._authed():
                        self._send_json(401, {"error": "unauthorized"})
                        return self._log_request(401)
                    return self._handle_job_action(job_id, action)
            self._send_json(404, {"error": "not found"})
            self._log_request(404)
        else:
            self._send_json(404, {"error": "not found"})
            self._log_request(404)

    # -- POST /v1/briefs --

    def _handle_submit(self) -> None:
        app = self.app
        if app.kill_event.is_set():
            self._send_json(503, {"error": "service unavailable: kill switch engaged"})
            return self._log_request(503)
        if not self._authed():
            self._send_json(401, {"error": "unauthorized"})
            return self._log_request(401)

        body, err = self._read_json()
        if err:
            self._send_json(400, {"error": err})
            return self._log_request(400)
        try:
            req = BriefRequest(**(body or {}))
        except ValidationError as e:
            self._send_json(400, {"error": "invalid request",
                                  "details": e.errors(include_url=False)})
            return self._log_request(400)

        # Idempotency first: a duplicate never consumes budget or a slot.
        idem_key = self.headers.get("Idempotency-Key")
        if idem_key:
            rec = app.idem.lookup(idem_key)
            if rec is not None:
                job = app.store.get_job(rec["job_id"])
                if job is not None:
                    self._send_json(200, {**_public_job(job), "duplicate": True})
                    app.logger.log("duplicate_request", idem_key=idem_key,
                                   job_id=job["job_id"])
                    return self._log_request(200)

        budget_err = check_budgets(req.question, app.config.per_request_token_limit,
                                   app.store.spend_tokens,
                                   app.config.global_token_budget)
        if budget_err:
            self._send_json(429, {"error": budget_err})
            return self._log_request(429)

        job_id = uuid.uuid4().hex
        if not app.try_acquire_slot(job_id):
            self._send_json(429, {"error": "concurrency limit reached"})
            return self._log_request(429)

        code, resp = app.submit(job_id, req.question, idem_key)
        self._send_json(int(code), resp)
        self._log_request(int(code), job_id=resp["job_id"])

    # -- job actions --

    def _handle_job_action(self, job_id: str, action: str) -> None:
        app = self.app
        if "/" in job_id:
            self._send_json(404, {"error": "unknown job"})
            return self._log_request(404)
        job = app.store.get_job(job_id)
        if job is None:
            self._send_json(404, {"error": "unknown job"})
            return self._log_request(404)

        if action == "retry":
            if app.kill_event.is_set():
                self._send_json(503, {"error": "service unavailable: kill switch engaged"})
                return self._log_request(503)
            if job["status"] != "failed":
                self._send_json(409, {"error": "only failed jobs can be retried"})
                return self._log_request(409)
            budget_err = check_budgets(job["question"],
                                       app.config.per_request_token_limit,
                                       app.store.spend_tokens,
                                       app.config.global_token_budget)
            if budget_err:
                self._send_json(429, {"error": budget_err})
                return self._log_request(429)
            if not app.try_acquire_slot(job_id):
                self._send_json(429, {"error": "concurrency limit reached"})
                return self._log_request(429)
            app.store.requeue(job_id)
            app._queue.put(job_id)
            app.logger.log("job_retried", job_id=job_id)
            self._send_json(202, {"job_id": job_id, "status": "queued"})
            self._log_request(202, job_id=job_id)
        else:  # approve / reject
            decision = "approved" if action == "approve" else "rejected"
            updated = app.store.record_decision(job_id, decision)
            if updated is None:
                self._send_json(409, {"error": "job is not completed"})
                return self._log_request(409)
            app.logger.log("job_decision", job_id=job_id, decision=decision)
            self._send_json(200, {"job_id": job_id, "decision": decision})
            self._log_request(200, job_id=job_id)

    # -- quiet the default stderr chatter; structured logs carry it --

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ANN001
        pass


def make_server(data_dir: str | Path,
                config: ServiceConfig | None = None,
                policy_factory: Callable[[Any], Any] | None = None,
                registry_factory: Callable[[Any], Any] | None = None,
                port: int = 0) -> tuple[ThreadingHTTPServer, App]:
    """Build (server, app). Port 0 = ephemeral, for tests."""
    app = App(data_dir, config=config, policy_factory=policy_factory,
              registry_factory=registry_factory)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.app = app  # type: ignore[attr-defined]
    return server, app
