# Demo script — Client Operations Copilot (5 minutes)

Run from a clean checkout of `agentic-ai-lab/lab-12`. No API key, no network
needed after setup. All commands are ordinary bash; a test
(`test_demo_reproduces_from_clean_checkout`) replays them in a fresh copy.

## 0:00 — Setup (30s)

```bash
cd lab-12
python3 -m venv .venv && .venv/bin/pip install -q pydantic pytest
export PYTHONPATH=src:../lab-02/src
```

## 0:30 — Run one exception through the copilot (1 min)

`data/demo_case.json` is an SLA breach: the dashboard was down for two hours.

```bash
.venv/bin/python -m lab12.run data/demo_case.json --out /tmp/lab12-demo
```

You will see: terminal `queued_for_approval`, risk `medium`, the policy
sections it cited, the queued action, and where the artifact and queue went.

## 1:30 — Read the artifact (1 min)

```bash
cat /tmp/lab12-demo/incident-INC-DEMO.md
```

This is the client-ready deliverable: risk, verbatim policy quotes, proposed
next steps, and — clearly marked — the actions that were NOT executed.

## 2:30 — Nothing runs without approval (1 min)

The queue file lists the proposed vendor call as `pending`:

```bash
cat /tmp/lab12-demo/queue.json
```

No email was sent, no one was called. Approving is a separate, deliberate step:

```bash
.venv/bin/python -c "
from lab12.approvals import ApprovalQueue
q = ApprovalQueue('/tmp/lab12-demo/queue.json')
print(q.approve('q001'))
"
```

Only now does the action execute — exactly once, recorded in the audit trail.

## 3:30 — Ambiguity asks, it doesn't guess (30s)

A case with no description gets questions, not a fabricated answer:

```bash
.venv/bin/python -c "
import json
json.dump({'id':'INC-X','type':'billing_dispute','client_id':'demo-customer'}, open('/tmp/bad.json','w'))
"
.venv/bin/python -m lab12.run /tmp/bad.json --out /tmp/lab12-demo-bad
```

Terminal: `needs_clarification`, with the missing field named.

## 4:00 — Outage degrades, it doesn't crash (30s)

```bash
.venv/bin/python -m lab12.run data/demo_case.json --out /tmp/lab12-demo-out --outage
```

Terminal: `degraded`, with a clear reason. No improvised policy, no crash.

## 4:30 — The full rehearsal (30s)

Twelve cases — normal, ambiguous, malicious (injection inside the text), and
outage — each checked against its expected terminal state and risk:

```bash
.venv/bin/python -m lab12.eval data/rehearsal_cases.json --out /tmp/lab12-demo-eval
.venv/bin/python -m pytest tests -q
```

Expected: `12/12 rehearsal cases passed`, then the acceptance suite.
