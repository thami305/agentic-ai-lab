# Cost model

Token counts are **measured**, not guessed: every `CopilotResult` records
`token_usage` per stage, and the table below is the average across the 12
rehearsal runs. The estimator is `ceil(chars / 4)` — an approximation,
documented as such in `copilot.py`. Dollar figures use a reference price of
$3.00 per million input tokens (a mid-tier hosted model); swap in your own
rate and the arithmetic still holds.

## Tokens per case, by terminal state

| Stage | resolved (n=3) | queued_for_approval (n=5) | needs_clarification (n=3) | degraded (n=1) |
|---|---|---|---|---|
| intake | 45 | 52 | 23 | 34 |
| retrieve | 81 | 111 | — | — |
| classify | 27 | 34 | — | — |
| propose | 46 | 57 | — | — |
| draft (incident summary) | 265 | 329 | — | — |
| **total per case** | **~464** | **~583** | **~23** | **~34** |

Notes:

- The **draft dominates**: roughly 55–60% of every full run is the incident
  summary. Shorter summaries are the cheapest optimization available.
- Malicious cases are the most expensive (~670 tokens): the injection gets
  quoted verbatim in the artifact and adds a next step. The security feature
  costs about 90 extra tokens per case — cheap insurance.
- Clarification and degradation are nearly free (~25–35 tokens): they stop
  before retrieval, classification, and drafting. Failing fast is cheap.

## What a month looks like

Assume 1,000 exceptions/month with a plausible mix:
70% resolved, 20% queued for approval, 7% needs clarification, 3% degraded.

| Item | Tokens |
|---|---|
| 700 resolved × 464 | 324,800 |
| 200 queued × 583 | 116,600 |
| 70 clarification × 23 | 1,610 |
| 30 degraded × 34 | 1,020 |
| **Monthly total** | **~444,000** |

At $3.00 / 1M tokens: **≈ $1.33 / month** for a thousand cases. The copilot's
cost is noise next to one human triage hour. If you plug in a real model
behind `propose_next_steps`, re-measure: model wording replaces the template
stage, and the draft stage will grow with model verbosity. The per-stage
recording makes that re-measurement a one-command job (`lab12.eval` prints
totals).

## Levers

1. Shorten the incident template — the draft is 60% of spend.
2. Cap retrieval at fewer, shorter quotes — retrieve is the second cost.
3. Cache: identical exception types against an unchanged policy set need not
   re-run retrieval at all (not implemented; see roadmap).
