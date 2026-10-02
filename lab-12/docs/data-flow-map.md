# Data flow map

Every place data enters, transforms, or leaves the copilot. "Trust" says
whether the pipeline may act on it.

| # | Stage | Input | Output | Trust |
|---|---|---|---|---|
| 1 | Intake | JSON file on disk (`run.py`) | `Intake` model or `ValidationError` | Untrusted until pydantic accepts it |
| 2 | Description text | Reporter's free text | Quoted in artifact; scanned for injection patterns | **Never trusted as instruction** — data only |
| 3 | Policy load | `data/policies.json` | `PolicyStore` (validated pydantic models) | Trusted after schema validation; file is local and versioned |
| 4 | Retrieval | query keywords + policy sections | `Citation{policy_id, section, quote}` | Quote must be a verbatim substring of the store; `full_text()` can re-verify |
| 5 | Classification | `Intake` fields | `(risk, rule_name)` | Deterministic rules; no model involved |
| 6 | Proposer | risk + citations + injection flag | `next_steps` wording | Template stub; wording only — cannot change risk, terminal, or queue |
| 7 | Router | risk, queued actions, intake validity, store health | terminal state | Pure function of the above; four terminals only |
| 8 | Artifact | all of the above | `incident-<id>.md` on disk | Read-only output; safe to share |
| 9 | Queue write | proposed actions | `queue.json` entry, status `pending` | Nothing executes at queue time — by construction |
| 10 | Approval | human decision | `approve()` executes the action once; `reject()` marks rejected | The only path to execution; audited in `EXECUTED_AUDIT` and the queue file |

## What never flows where

- Reporter text never flows into an action's arguments. Payloads are built by
  `_build_payload()` from typed `Intake` fields only.
- Model-proposed wording never flows into risk, terminal, or queue decisions.
- A rejected or already-executed queue entry can never flow back into
  `approve()` — the status/executed check raises first.

## PII note

Descriptions may contain PII (SSNs in the breach rehearsal). The artifact
quotes the description verbatim, so PII lands in the incident file. Per
POL-DATA the summaries inherit a 2-year retention; a production system would
redact before writing. The lab keeps the quote verbatim on purpose — the
injection rehearsal needs to show exactly what was said — and the runbook
covers handling.
