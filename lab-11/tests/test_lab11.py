"""Lab 11 acceptance tests: a real HTTP server on localhost, real urllib.

Every test starts the service in a thread on an ephemeral port with its own
data dir, talks to it over real HTTP, and shuts it down. Backends are
deterministic stubs (lab-02's OracleStub plus small test doubles) — no API
key, no external network.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lab02.models import ModelError, OracleStub
from lab11.config import CURRENT_VERSION, ServiceConfig, load_config
from lab11.jobs import JobStore
from lab11.limits import JobAborted, JobKilled
from lab11.log import JsonLogger, redact
from lab11.server import make_server

TEST_TOKEN = "test-bearer-token"
QUESTION = "How utilized is Northwind's current warehouse?"
DECLINE_QUESTION = "What is the CEO's total compensation?"
FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- helpers ---

def http(base, method, path, body=None, headers=None, token=TEST_TOKEN,
         raw_body=None):
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None)
    h = dict(headers or {})
    if body is not None or raw_body is not None:
        h.setdefault("Content-Type", "application/json")
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=h)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None, dict(e.headers)
        except json.JSONDecodeError:
            return e.code, raw.decode(errors="replace"), dict(e.headers)


@contextlib.contextmanager
def running_server(data_dir=None, config=None, policy_factory=None,
                   registry_factory=None):
    tmp = None
    if data_dir is None:
        tmp = tempfile.TemporaryDirectory()
        data_dir = tmp.name
    else:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
    cfg = config or ServiceConfig(token=TEST_TOKEN)
    server, app = make_server(data_dir, config=cfg,
                              policy_factory=policy_factory,
                              registry_factory=registry_factory)
    app.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", app
    finally:
        app.stop()
        server.shutdown()
        server.server_close()
        if tmp is not None:
            tmp.cleanup()


def wait_for_job(base, job_id, statuses=("completed", "failed"), timeout=25):
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        code, body, _ = http(base, "GET", f"/v1/briefs/{job_id}")
        assert code == 200, body
        if body["status"] in statuses:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {statuses}: {body}")


def wait_for_status(base, job_id, status, timeout=25):
    return wait_for_job(base, job_id, statuses=(status,), timeout=timeout)


def submit(base, question=QUESTION, key=None, token=TEST_TOKEN):
    headers = {"Idempotency-Key": key} if key else None
    return http(base, "POST", "/v1/briefs", {"question": question},
                headers=headers, token=token)


# ---------------------------------------------------------------- doubles ---

class SlowBackend:
    """OracleStub that sleeps once, aborting promptly on kill/stop."""

    def __init__(self, ctx, sleep_s=4.0):
        self._inner = OracleStub()
        self._ctx = ctx
        self._sleep_s = sleep_s
        self._slept = False

    def start_run(self, system, request, tools):
        self._inner.start_run(system, request, tools)

    def observe_tool_results(self, results):
        self._inner.observe_tool_results(results)

    def next(self):
        if not self._slept:
            self._slept = True
            end = time.monotonic() + self._sleep_s
            while time.monotonic() < end:
                if self._ctx.kill_event.is_set():
                    raise JobKilled("kill switch engaged")
                if self._ctx.stopped.is_set():
                    raise JobAborted("server stopping")
                time.sleep(0.05)
        return self._inner.next()


class FailOnceBackend:
    """Simulates a model outage on the first call, then recovers."""

    def __init__(self):
        self._inner = OracleStub()
        self.outages = 1

    def start_run(self, system, request, tools):
        self._inner.start_run(system, request, tools)

    def observe_tool_results(self, results):
        self._inner.observe_tool_results(results)

    def next(self):
        if self.outages > 0:
            self.outages -= 1
            raise ModelError("upstream model unavailable (simulated outage)")
        return self._inner.next()


def exploding_registry(packet):
    """lab-02 registry whose get_passage tool blows up mid-run."""
    from lab02.tools import ToolDef, build_registry
    reg = build_registry(packet)
    tool = reg.get("get_passage")

    def down(**kwargs):
        raise RuntimeError("passage store exploded mid-run")

    reg.register(ToolDef(name=tool.name, description=tool.description,
                         args_model=tool.args_model, fn=down,
                         timeout_s=tool.timeout_s, max_retries=0))
    return reg


# ------------------------------------------------------------------- tests ---

def test_healthz_reports_status_uptime_queue_and_spend():
    with running_server() as (base, app):
        code, body, _ = http(base, "GET", "/healthz", token=None)
        assert code == 200
        assert body["status"] == "ok"
        assert body["killed"] is False
        assert body["uptime_s"] >= 0
        assert body["queue_depth"] == 0
        assert body["spend_tokens"] == 0
        assert body["token_budget"] == 100_000
        assert body["jobs"] == {"queued": 0, "running": 0,
                                "completed": 0, "failed": 0}


def test_auth_required_and_secrets_redacted_in_logs():
    fake_key = "sk-fake-test-key-abcdef123456"
    with running_server() as (base, app):
        code, body, _ = http(base, "POST", "/v1/briefs",
                             {"question": QUESTION}, token=None)
        assert code == 401
        assert body["error"] == "unauthorized"

        code, _, _ = http(base, "POST", "/v1/briefs",
                          {"question": QUESTION}, token="wrong-token")
        assert code == 401

        # A request carrying a key-like secret must not leak it into the logs.
        code, _, _ = http(base, "POST", "/v1/briefs",
                          {"question": QUESTION}, token=fake_key)
        assert code == 401

        log_text = (app.data_dir / "server.log.jsonl").read_text()
        assert fake_key not in log_text
        assert "[REDACTED]" in log_text


def test_submit_and_get_completed_brief():
    with running_server() as (base, app):
        code, body, _ = submit(base)
        assert code == 202
        job_id = body["job_id"]
        assert body["status"] == "queued"

        job = wait_for_job(base, job_id)
        assert job["status"] == "completed"
        assert job["brief"] is not None
        assert job["brief"]["question"] == QUESTION
        assert len(job["brief"]["claims"]) >= 1
        assert job["tokens_used"] == 3300  # 3 oracle turns x 1100

        code, listed, _ = http(base, "GET", "/v1/briefs")
        assert code == 200
        assert any(j["job_id"] == job_id for j in listed["jobs"])


def test_invalid_payload_returns_400_with_details():
    with running_server() as (base, app):
        code, body, _ = http(base, "POST", "/v1/briefs", {"question": "abc"})
        assert code == 400
        assert body["error"] == "invalid request"
        assert body["details"]

        code, body, _ = http(base, "POST", "/v1/briefs", {})
        assert code == 400

        code, body, _ = http(base, "POST", "/v1/briefs",
                             raw_body=b"{not valid json")
        assert code == 400
        assert "invalid JSON" in body["error"]


def test_duplicate_idempotency_key_runs_once():
    with running_server() as (base, app):
        code1, first, _ = submit(base, key="key-abc")
        code2, second, _ = submit(base, key="key-abc")
        assert code1 == 202
        assert code2 == 200
        assert second["duplicate"] is True
        assert first["job_id"] == second["job_id"]

        job = wait_for_job(base, first["job_id"])
        assert job["status"] == "completed"
        # Third read, same key: still the original job, still one execution.
        _, third, _ = submit(base, key="key-abc")
        assert third["job_id"] == first["job_id"]
        assert app.executions == 1


def test_expired_idempotency_key_reexecutes():
    cfg = ServiceConfig(token=TEST_TOKEN, idempotency_ttl_s=0.5)
    with running_server(config=cfg) as (base, app):
        _, first, _ = submit(base, key="ttl-key")
        job1 = wait_for_job(base, first["job_id"])
        assert job1["status"] == "completed"
        time.sleep(0.8)  # let the key expire
        code, second, _ = submit(base, key="ttl-key")
        assert code == 202
        assert second["job_id"] != first["job_id"]
        job2 = wait_for_job(base, second["job_id"])
        assert job2["status"] == "completed"
        assert app.executions == 2


def test_unknown_job_returns_404():
    with running_server() as (base, _):
        code, body, _ = http(base, "GET", "/v1/briefs/no-such-job")
        assert code == 404
        assert body["error"] == "unknown job"


def test_approve_and_reject_completed_job():
    with running_server() as (base, _):
        _, body, _ = submit(base)
        job = wait_for_job(base, body["job_id"])

        code, resp, _ = http(base, "POST",
                             f"/v1/briefs/{job['job_id']}/approve")
        assert code == 200
        assert resp["decision"] == "approved"

        code, job2, _ = http(base, "GET", f"/v1/briefs/{job['job_id']}")
        assert code == 200
        assert job2["decision"] == "approved"

        code, resp, _ = http(base, "POST",
                             f"/v1/briefs/{job['job_id']}/reject")
        assert code == 200
        assert resp["decision"] == "rejected"


def test_approve_noncompleted_job_returns_409():
    backend = FailOnceBackend()
    with running_server(policy_factory=lambda ctx: backend) as (base, _):
        _, body, _ = submit(base)
        job = wait_for_job(base, body["job_id"])
        assert job["status"] == "failed"
        code, resp, _ = http(base, "POST",
                             f"/v1/briefs/{job['job_id']}/approve")
        assert code == 409
        assert "not completed" in resp["error"]


def test_model_outage_fails_job_and_retry_recovers():
    backend = FailOnceBackend()
    with running_server(policy_factory=lambda ctx: backend) as (base, app):
        _, body, _ = submit(base)
        job = wait_for_job(base, body["job_id"])
        assert job["status"] == "failed"
        assert "model_error" in job["error"]
        assert job["brief"] is None

        code, resp, _ = http(base, "POST",
                             f"/v1/briefs/{body['job_id']}/retry")
        assert code == 202
        job2 = wait_for_job(base, body["job_id"])
        assert job2["status"] == "completed"
        assert job2["brief"] is not None
        assert job2["attempts"] == 2


def test_tool_outage_fails_with_no_partial_result():
    with running_server(registry_factory=exploding_registry) as (base, _):
        _, body, _ = submit(base)
        job = wait_for_job(base, body["job_id"])
        assert job["status"] == "failed"
        assert job["brief"] is None
        assert job["declined"] is None
        assert job["error"]  # the outage, not a silent drop


def test_slow_dependency_hits_request_timeout():
    cfg = ServiceConfig(token=TEST_TOKEN, request_timeout_s=1.0)
    slow = lambda ctx: SlowBackend(ctx, sleep_s=6.0)  # noqa: E731
    with running_server(config=cfg, policy_factory=slow) as (base, _):
        _, body, _ = submit(base)
        job = wait_for_job(base, body["job_id"], timeout=10)
        assert job["status"] == "failed"
        assert "timeout" in job["error"]
        assert job["brief"] is None


def test_concurrency_limit_returns_429_over_limit():
    cfg = ServiceConfig(token=TEST_TOKEN, concurrency_limit=2)
    slow = lambda ctx: SlowBackend(ctx, sleep_s=4.0)  # noqa: E731
    with running_server(config=cfg, policy_factory=slow) as (base, _):
        c1, j1, _ = submit(base)
        c2, j2, _ = submit(base)
        c3, over, _ = submit(base)
        assert (c1, c2) == (202, 202)
        assert c3 == 429
        assert "concurrency" in over["error"]
        # The two accepted jobs still run to completion.
        assert wait_for_job(base, j1["job_id"])["status"] == "completed"
        assert wait_for_job(base, j2["job_id"])["status"] == "completed"


def test_per_request_token_budget_returns_429():
    cfg = ServiceConfig(token=TEST_TOKEN, per_request_token_limit=50)
    with running_server(config=cfg) as (base, app):
        code, body, _ = submit(base)
        assert code == 429
        assert "per-request token budget" in body["error"]
        assert app.executions == 0


def test_global_spend_budget_blocks_when_exhausted():
    cfg = ServiceConfig(token=TEST_TOKEN, global_token_budget=4000)
    with running_server(config=cfg) as (base, app):
        _, first, _ = submit(base)
        job = wait_for_job(base, first["job_id"])
        assert job["status"] == "completed"

        code, body, _ = http(base, "GET", "/healthz", token=None)
        assert body["spend_tokens"] == 3300  # persisted spend counter

        code, body, _ = submit(base, key="second")
        assert code == 429
        assert "global token budget" in body["error"]


def test_kill_switch_aborts_inflight_and_blocks_new():
    slow = lambda ctx: SlowBackend(ctx, sleep_s=30.0)  # noqa: E731
    with running_server(policy_factory=slow) as (base, _):
        _, body, _ = submit(base)
        wait_for_status(base, body["job_id"], "running")

        code, resp, _ = http(base, "POST", "/admin/kill")
        assert code == 200
        assert resp["killed"] is True

        job = wait_for_job(base, body["job_id"])
        assert job["status"] == "failed"
        assert "kill" in job["error"]

        code, resp, _ = submit(base)
        assert code == 503
        assert "kill" in resp["error"]

        code, health, _ = http(base, "GET", "/healthz", token=None)
        assert code == 200
        assert health["killed"] is True


def test_restart_recovers_running_job_from_durable_state():
    with tempfile.TemporaryDirectory() as data_dir:
        cfg = ServiceConfig(token=TEST_TOKEN)
        slow = lambda ctx: SlowBackend(ctx, sleep_s=30.0)  # noqa: E731
        with running_server(data_dir=data_dir, config=cfg,
                            policy_factory=slow) as (base, _):
            _, body, _ = submit(base)
            job_id = body["job_id"]
            wait_for_status(base, job_id, "running")
            # Exiting the context stops the server mid-job: the jobs.json
            # record is left in "running", exactly like a crash.

        with running_server(data_dir=data_dir, config=cfg) as (base2, app2):
            job = wait_for_job(base2, job_id)
            assert job["status"] == "completed"
            assert job["brief"] is not None
            assert job["brief"]["question"] == QUESTION
            assert app2.executions == 1  # the recovered run, once


def test_state_schema_migration_v1_to_v2():
    with tempfile.TemporaryDirectory() as data_dir:
        shutil.copy(FIXTURES / "state-v1.json", Path(data_dir) / "jobs.json")
        store = JobStore(Path(data_dir) / "jobs.json")

        done = store.get_job("v1-job-done")
        assert done["status"] == "completed"
        assert done["brief"]["sources_used"] == ["DOC-OPS"]
        assert done["attempts"] == 1

        pending = store.get_job("v1-job-pending")
        assert pending["status"] == "queued"

        failed = store.get_job("v1-job-failed")
        assert failed["status"] == "failed"
        assert "model_error" in failed["error"]

        assert store.spend_tokens == 0

        raw = json.loads((Path(data_dir) / "jobs.json").read_text())
        assert raw["version"] == 2
        assert set(raw["jobs"]) == {"v1-job-done", "v1-job-pending",
                                   "v1-job-failed"}


def test_config_rollback_previous_version_loads_with_defaults():
    cfg = load_config(FIXTURES / "config-v1.json")
    assert cfg.version == CURRENT_VERSION
    assert cfg.token == "old-config-token"
    assert cfg.port == 8123
    # v1 knew nothing about these; defaults fill them in.
    assert cfg.concurrency_limit == 2
    assert cfg.request_timeout_s == 30.0
    assert cfg.per_request_token_limit == 6000
    assert cfg.global_token_budget == 100_000
    assert cfg.idempotency_ttl_s == 3600.0


def test_log_redaction_unit():
    assert redact({"authorization": "Bearer abc"}) == {
        "authorization": "[REDACTED]"}
    assert redact({"api_key": "sk-live-123"})["api_key"] == "[REDACTED]"
    assert "sk-live-123" not in redact({"note": "key sk-live-123 leaked"})
    # Ordinary values pass through untouched.
    assert redact({"job_id": "abc123", "n": 5}) == {"job_id": "abc123", "n": 5}

    with tempfile.TemporaryDirectory() as data_dir:
        log = JsonLogger(Path(data_dir) / "t.log.jsonl")
        log.log("request", headers={"Authorization": "Bearer sk-fake-xyz-789"},
                question="hello")
        lines = (Path(data_dir) / "t.log.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "request"
        assert "sk-fake-xyz-789" not in lines[0]
        assert record["headers"]["Authorization"] == "[REDACTED]"


def test_review_ui_serves_html_with_api_buttons():
    with running_server() as (base, _):
        req = urllib.request.Request(base + "/")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            html = resp.read().decode()
        assert "fetch(" in html
        assert "approve" in html and "reject" in html
        assert "/v1/briefs" in html


def test_decline_is_completed_not_failed():
    with running_server() as (base, _):
        _, body, _ = submit(base, question=DECLINE_QUESTION)
        job = wait_for_job(base, body["job_id"])
        assert job["status"] == "completed"
        assert job["brief"] is None
        assert job["declined"] is not None
        assert len(job["declined"]["reason"]) > 0
