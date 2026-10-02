# Lab 11 — The brief pipeline as a production-shaped service

Week 11 of the Agentic AI field plan. Lab 2's deterministic brief pipeline,
wrapped in a real HTTP service: bearer auth, idempotency keys, token budgets,
a kill switch, durable state with crash recovery, structured logs, and a
review UI. Stdlib `http.server` only — no web framework.

The doctrine hasn't changed: the model proposes, deterministic code decides.
Now the deterministic code also decides who may ask, how much they may spend,
and when everything stops.

## Quickstart

```bash
cd agentic-ai-lab/lab-11
python3 -m venv .venv && .venv/bin/pip install -q pydantic pytest

# start the service (reuses lab-02/lab-03 via PYTHONPATH; nothing copied)
PYTHONPATH=src:../lab-02/src:../lab-03/src \
  .venv/bin/python -m lab11.run --port 8000 --data-dir data --token dev-token

# in another shell
curl localhost:8000/healthz
curl -X POST localhost:8000/v1/briefs \
  -H "Authorization: Bearer dev-token" -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-1" \
  -d '{"question":"How utilized is Northwind'"'"'s current warehouse?"}'
# -> {"job_id": "...", "status": "queued"} ; poll GET /v1/briefs/<id>

# run the 22 acceptance tests (real HTTP against localhost, stub backends)
PYTHONPATH=src:../lab-02/src:../lab-03/src .venv/bin/python -m pytest tests -q
```

Open `http://localhost:8000/` for the review UI: job list plus
approve/reject buttons and a submit form.

## Layout

```
lab-11/
  src/lab11/
    server.py    # routes, auth, budgets, dispatcher, App lifecycle
    worker.py    # background pipeline: kill-checked stage boundaries,
                 #   request timeout, timeout-abandoned threads can't clobber
    jobs.py      # JobStore: atomic JSON persistence, v1->v2 migration,
                 #   crash recovery (running -> queued)
    idempotency.py  # key store with TTL; duplicates never re-run
    limits.py    # token estimate, per-request + global budgets, timeouts
    auth.py      # bearer check (constant-time compare)
    log.py       # JSON-lines logger with secret redaction
    config.py    # versioned config; old versions load with defaults filled
    ui.py        # the static review page
    run.py       # CLI: python -m lab11.run --port 8000 --data-dir data
  tests/
    test_lab11.py        # 22 acceptance tests, real HTTP, deterministic stubs
    fixtures/
      state-v1.json      # old-shape state file for the migration test
      config-v1.json     # previous-version config for the rollback test
  docs/architecture.md   # design notes, honest caveats, test report
  data/                  # runtime: jobs.json, server.log.jsonl (gitignored)
```

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/briefs` | Bearer auth. `Idempotency-Key` header supported. 202 + `job_id`; 400/401/429/503 |
| `GET` | `/v1/briefs` | Bearer auth. Job list (feeds the review UI) |
| `GET` | `/v1/briefs/{id}` | `queued`/`running`/`completed`/`failed` + brief/decline or error |
| `POST` | `/v1/briefs/{id}/retry` | Requeues a failed job |
| `POST` | `/v1/briefs/{id}/approve` | Records approval (job must be completed) |
| `POST` | `/v1/briefs/{id}/reject` | Records rejection (job must be completed) |
| `GET` | `/healthz` | status, uptime, queue depth, spend counters, job counts |
| `POST` | `/admin/kill` | Bearer auth. One-way kill switch |
| `GET` | `/` | Review UI (static HTML, fetch() calls the API) |

## What "done" means (from the plan)

- [x] Service recovers predictably — kill the process mid-job; on restart the
      job resumes from durable state (test: `test_restart_recovers_running_job_from_durable_state`)
- [x] Never duplicates an action — same `Idempotency-Key` twice runs the
      pipeline exactly once (execution counter == 1); expired keys re-execute
- [x] Exposes useful health signals — `/healthz` reports uptime, queue depth,
      spend vs budget, per-status job counts, kill state
- [x] Supports rollback — previous-version config files load with defaults
      filled; v1 state files migrate to v2 on load
- [x] Kill switch aborts in-flight work at the next stage boundary and new
      requests get 503 afterwards
- [x] Budgets enforced — per-request token limit and persisted global spend
      counter both refuse with 429; concurrency semaphore refuses with 429
- [x] Structured JSON-lines logs with bearer tokens and key-like values redacted
- [ ] Load/soak test against a real model backend — stubs only so far
