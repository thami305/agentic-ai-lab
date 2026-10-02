# Lab 11 architecture

## The idea

Labs 1–3 proved the loop in-process: the model proposes, deterministic code
decides. Lab 11 asks what that loop needs to survive contact with production:
identity, money, failure, and restarts. The answer is a thin, boring,
auditable shell around the unchanged lab-02 pipeline — stdlib `http.server`,
one JSON state file, one JSON-lines log.

The pipeline itself is untouched. `worker.py` builds lab-02's `Agent` with the
injected backend (default: the deterministic `OracleStub`) and the lab-02
tool registry, then runs it through four stages — pre, run, validate,
publish — checking the kill flag at each boundary. Everything production-ish
lives *around* the run, never inside the agent's decisions.

## Design notes

**Jobs, not requests.** `POST /v1/briefs` returns 202 immediately; the brief
runs on a background worker thread. Job records (`queued → running →
completed|failed`) persist to `data/jobs.json` with atomic writes (temp file +
`os.replace`). A decline is a *completed* job with a `declined` payload, not a
failure — the pipeline did its job and the honest answer was "the packet can't
say."

**Idempotency is checked before money and slots.** A duplicate
`Idempotency-Key` returns the original job without consuming budget or a
concurrency slot. Keys carry a TTL (default 1h); expired keys are pruned on
read and treated as new submissions. The tests prove non-duplication with an
in-memory execution counter: two submits, one run.

**Crash recovery, not crash avoidance.** On boot, `JobStore.recover()` moves
`running` jobs back to `queued`, and `App.start()` re-enqueues everything
still queued (the in-memory queue doesn't survive a restart; the store does).
Recovered jobs acquire a concurrency slot in the dispatcher — never
double-counted, because slot ownership is tracked per process in
`_slots_held`. `finish_job` only transitions out of `running`, so a late
thread (a timeout-abandoned run, or a pre-crash worker that somehow wakes up)
can never clobber a recorded outcome. Re-running is safe because the pipeline
is deterministic: same question, same brief, no duplicated side effect.

**Kill switch.** A `threading.Event`, one-way. The dispatcher refuses to start
queued jobs after the kill (marks them failed); the worker checks the flag
between stages; the test slow-backend also watches it mid-sleep, so in-flight
work aborts within ~50ms. New submissions get 503. `/healthz` keeps working
and reports `"killed": true` — the kill switch must be observable, not silent.

**Budgets.** Pre-run estimate is fixed and deterministic (1500 tokens; the
oracle's real usage is 3300). Over the per-request limit → 429. Estimate that
would push persisted spend over the global budget → 429. Actual tokens are
added to the spend counter on completion (and on failure, when the model did
real work). `/healthz` exposes spend vs budget.

**Timeouts.** The agent runs on a child thread; the worker joins with
`request_timeout_s`. On expiry the job fails with a timeout error and the
abandoned thread's eventual result is discarded — no partial result is ever
published.

**Logs.** One JSON line per request and per job transition. `log.redact`
scrubs bearer/authorization headers, sensitive field names, and `sk-…`-shaped
values anywhere they appear. Tested with a fake key.

**Config & state versioning.** Config carries `version`; v1 files (host/port/
token only) load with v2 defaults filled — that *is* the rollback story: check
out the old config, boot, keep serving. State files migrate v1 → v2 on load
and are written back in the new shape (`tests/fixtures/` holds both).

## Honest caveats

- **The review UI embeds the bearer token** in the served HTML so the demo
  works with zero setup. In front of real users this page would sit behind the
  operator's own login. Documented in `ui.py`; not something to ship as-is.
- **Auth is one shared secret**, not per-client credentials. Fine for an
  operator tool, not for multi-tenant use.
- **The kill switch is one-way** until restart. Deliberate — a kill you can
  accidentally un-kill isn't a kill switch — but it means a false trigger
  needs a redeploy.
- **Timeout abandonment leaks the model thread** until it finishes (daemon
  thread; its result is discarded). With a real streaming model you'd want
  cooperative cancellation, not abandonment.
- **Budgets use a fixed estimate**, not a live meter. A pathological prompt
  inside the 500-char question cap can't blow past it far, but this is
  cost *governance*, not cost *accounting*.
- **Single process, single JSON file.** No leader election, no horizontal
  scale. The state file would need SQLite/WAL (or a real queue) before two
  writers touch it.

## Test report

22 tests, all deterministic: real HTTP via `urllib` against a
`ThreadingHTTPServer` on an ephemeral port in a thread, per-test temp data
dir, stub backends only — no API key, no network.

```
test_healthz_reports_status_uptime_queue_and_spend          PASS
test_auth_required_and_secrets_redacted_in_logs             PASS
test_submit_and_get_completed_brief                         PASS
test_invalid_payload_returns_400_with_details                PASS
test_duplicate_idempotency_key_runs_once                    PASS
test_expired_idempotency_key_reexecutes                     PASS
test_unknown_job_returns_404                                PASS
test_approve_and_reject_completed_job                       PASS
test_approve_noncompleted_job_returns_409                   PASS
test_model_outage_fails_job_and_retry_recovers              PASS
test_tool_outage_fails_with_no_partial_result               PASS
test_slow_dependency_hits_request_timeout                   PASS
test_concurrency_limit_returns_429_over_limit               PASS
test_per_request_token_budget_returns_429                   PASS
test_global_spend_budget_blocks_when_exhausted               PASS
test_kill_switch_aborts_inflight_and_blocks_new             PASS
test_restart_recovers_running_job_from_durable_state        PASS
test_state_schema_migration_v1_to_v2                        PASS
test_config_rollback_previous_version_loads_with_defaults   PASS
test_log_redaction_unit                                     PASS
test_review_ui_serves_html_with_api_buttons                 PASS
test_decline_is_completed_not_failed                        PASS
```

22 passed in ~15s (`PYTHONPATH=src:../lab-02/src:../lab-03/src
.venv/bin/python -m pytest tests -q`, Python 3.12.3).

Two bugs were found and fixed during development, both in the service (not
the tests): request logging crashed on keyword args (`_log_request` signature),
and crash-recovered jobs were never re-enqueued because only the in-memory
queue fed the dispatcher — recovery now re-enqueues from the store and
re-acquires concurrency slots per process.
