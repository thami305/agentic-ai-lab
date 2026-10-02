# Runbook — operating the Client Operations Copilot

## Triage loop (daily)

1. Drop each new exception JSON into the intake directory.
2. Run the copilot per case:
   `python -m lab12.run case.json --out out/<case-id>`
3. Read the printed terminal state and act:
   - `resolved` — review the incident summary, send/file it, done.
   - `queued_for_approval` — open the summary, then review each queued
     action in `queue.json`. Approve only what the policy citations support.
   - `needs_clarification` — ask the reporter the named questions; re-run
     when they answer. Do not fill in the blanks yourself.
   - `degraded` — do not triage the case by hand from memory; fix the
     policy store first (below), then re-run.

## Approving or rejecting actions

```bash
python -c "
from lab12.approvals import ApprovalQueue
q = ApprovalQueue('out/<case-id>/queue.json')
print([ (e.id, e.action, e.status) for e in q.pending() ])
# after reviewing the incident summary:
q.approve('q001')   # executes once, audited
# or:
q.reject('q001', 'duplicate of q002')
"
```

Rules: approve only from `pending`; an entry executes at most once; a
rejected entry can never be executed afterwards. The audit trail is the queue
file itself plus the process `EXECUTED_AUDIT` log.

## Policy store outage

Symptoms: every case returns `degraded` with "policy store unavailable".

1. Check `data/policies.json` exists and parses: `python -m json.tool
   data/policies.json`.
2. Check the `LAB12_POLICY_OUTAGE` environment variable is not set to `1`
   (that is the drill switch, not a real outage).
3. Fix, then re-run the degraded cases — they were never classified, so
   nothing was decided on stale or missing policy.

## Injection flag

If the output notes "instruction-like text", open the artifact and read the
"Reporter's exact words" section. The text is quoted for transparency; the
copilot followed none of it. Treat the flag as a signal to read the case
carefully, not as a malfunction.

## Adding a policy or changing a risk rule

- Policies: edit `data/policies.json` (sections need `section` + `text`),
  then re-run `lab12.eval` — the rehearsal must still be 12/12.
- Risk rules: edit `RISK_RULES` in `src/lab12/risk.py` (keep the dict order:
  high before medium before low) and update the rationale text. The docs in
  `docs/architecture.md` describe the same rules — update both.
- New action types: add the function to `src/lab12/actions.py`, a payload
  builder in `copilot._build_payload`, and a plan entry in `_ACTION_PLANS`.
  The action is callable only via the queue — keep it that way.

## Handling PII

Incident summaries quote the reporter's description verbatim, so PII in a
report lands in the artifact. Store artifacts with the same access controls
as the intake directory, and honor the 2-year retention in POL-DATA. A
production deployment should redact SSNs/card numbers before writing; this
lab quotes verbatim deliberately so injection attempts stay visible.
