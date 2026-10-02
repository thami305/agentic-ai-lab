# Lab 12 — Client Operations Copilot (capstone)

Week 12 of the Agentic AI field plan. The capstone: a deterministic
operations copilot that triages business exceptions end to end — intake,
policy retrieval with verbatim citations, rule-based risk classification, a
drafted incident summary — and then **stops before doing anything
irreversible**. External or state-changing actions go to a persisted approval
queue; they execute only when a human approves, exactly once, and the tests
prove they never run any other way.

## Quickstart

```bash
cd agentic-ai-lab/lab-12
python3 -m venv .venv && .venv/bin/pip install -q pydantic pytest
export PYTHONPATH=src:../lab-02/src   # lab-12 reuses lab-02's keyword retrieval

# one exception -> terminal state, risk, citations, artifact, queue
.venv/bin/python -m lab12.run data/demo_case.json --out /tmp/lab12-demo

# ambiguous input -> asks instead of guessing (exit 2)
.venv/bin/python -m lab12.run /tmp/bad.json --out /tmp/lab12-bad

# policy-store outage -> graceful degradation (exit 3)
.venv/bin/python -m lab12.run data/demo_case.json --out /tmp/lab12-out --outage

# 12 rehearsal cases against expected terminals/risks
.venv/bin/python -m lab12.eval data/rehearsal_cases.json

# the 19 acceptance tests
.venv/bin/python -m pytest tests -q
```

## Layout

```
lab-12/
  src/lab12/
    intake.py      # Intake pydantic model; validation errors become questions
    policies.py    # PolicyStore (load/validate), retrieve() -> verbatim citations
    risk.py        # RISK_RULES documented dict + classify() (HIGH > MEDIUM > LOW)
    copilot.py     # pipeline: intake -> retrieve -> classify -> propose -> route
                   #   terminals: resolved | needs_clarification |
                   #              queued_for_approval | degraded
    approvals.py   # ApprovalQueue persisted to JSON; approve() runs once, reject() never
    actions.py     # the external/state-changing stubs; called ONLY via approve()
    artifacts.py   # render_incident_markdown()
    run.py         # CLI
    eval.py        # rehearsal runner (12 cases)
  data/
    policies.json          # 8 synthetic policies with sections
    rehearsal_cases.json   # 12 cases: normal, ambiguous, malicious, outage
    demo_case.json         # the demo walkthrough case
  tests/test_lab12.py      # 19 acceptance tests
  docs/
    demo-script.md         # 5-minute walkthrough (replayed by a test)
    architecture.md        # design notes + ASCII diagram + test report
    data-flow-map.md       # where data enters, transforms, leaves
    eval-report.md         # the 12 rehearsal results
    risk-register.md       # risk table; every control maps to a real test
    runbook.md             # operating the copilot
    cost-model.md          # measured token math per case type
    roadmap.md             # what v2 would add
    case-study.md          # one page, non-technical
```

## Terminals

| Condition | Terminal | Exit |
|---|---|---|
| Understood, nothing external needed | resolved | 0 |
| Proposed actions waiting on a human | queued_for_approval | 0 |
| Intake incomplete | needs_clarification | 2 |
| Policy store down | degraded | 3 |

Injection inside a description is treated as data: quoted verbatim in the
artifact, flagged, never followed — and any proposed action still waits in
the queue, never executed.

## What "done" means (from the plan)

- [x] Intake a business exception as JSON; retrieve relevant policies with
      passage citations (keyword retriever reused from lab-02)
- [x] Deterministic risk classification, rules documented in code and docs
- [x] Proposed next steps + a markdown incident artifact per case
- [x] Pause before any external/state-changing action: approval queue, never
      executed without approval (proven by spies in tests)
- [x] Rehearsed as tests: normal, ambiguous, malicious (injection as data),
      outage (graceful degradation) — each asserts the right terminal behavior
- [x] docs/ packaged: demo script, architecture, data-flow map, eval report,
      risk register (every control maps to a test — itself tested), runbook,
      cost model, roadmap, case study
- [x] Non-technical reader can state the value from the case study
      ("documented, policy-backed summaries in seconds; the machine can never
      act on its own")
- [x] Demo reproduces from a clean checkout (replayed by
      `test_demo_reproduces_from_clean_checkout`)
