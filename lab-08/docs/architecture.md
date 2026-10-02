# Lab 8 architecture

## The idea

Lab 8 puts three orchestration patterns on the same task and measures them
head-to-head instead of arguing about them: review a synthetic vendor
proposal (Pricing / Terms / Delivery-SLA, ~700 words, 9 passages with
planted issues — vague "best efforts" SLA, uncapped price escalation,
auto-renewal, missing liability cap, termination fee) into a structured
`Review`: verdict (accept/revise/reject), findings with severity and
verbatim evidence, risks.

The doctrine from labs 1–3 holds in every pattern: **the model proposes,
deterministic code decides.** Each pattern ends at the same ship gate —
`validate_review`: schema-valid `Review`, every finding citing a real
passage with a verbatim quote, and no "accept" verdict while a
high-severity finding is present. The verdict itself comes from one shared
deterministic rule, `verdict_for()`: ≥3 highs → reject; any high or medium
→ revise; otherwise accept.

## The three patterns

**A — single agent with tools.** A compact generic loop written for this
lab (`loop.py`, ~200 lines): allow-listed tools, Pydantic argument
validation before execution, two budgets (max turns, max tool calls),
duplicate-call caching, schema-validated final answer plus the deterministic
post-validator. It is generic over the final-answer schema — lab02's `Agent`
was not reused because it is hardcoded to `ResearchBrief`. Reuses lab02's
`ToolDef`/`ToolRegistry` and the `ModelResponse`/`ToolCallItem` protocol.

**B — manager + two specialists.** The manager routes pricing questions to
the PricingSpecialist and terms questions to the TermsSpecialist via a
deterministic `route_domain()`; handoffs are explicit typed `Handoff`
messages (from/to/task/context). Each specialist runs the same loop as A
against a *restricted* registry — pricing tools see Pricing passages only,
terms tools see Terms + Delivery/SLA only. A cross-domain call is rejected
by the allow-list (`unknown_tool` in the trace, never executed); the test
suite proves it. The manager merges deterministically: dedupe, severity
sort, `verdict_for()`. The specialists' own verdicts are discarded — the
manager owns the verdict.

**C — explicit graph.** Reuses `lab03.graph.Graph` with proposal-specific
state and nodes: validate → extract → assess → review → publish, plus a
conflict → human_review branch. `extract` is the model-driven node (seeded
retrieval policy, every tool call logged for measurement parity); the rest
is deterministic. Conflict means the *same claim* about the same passage
with different severities — two *different* findings sharing a passage is
normal, not a conflict (an earlier, coarser detector misfired on the SLA
passage and was fixed). The graph path is recorded on state; tests assert
on it directly.

## The stubs

- `OracleStub`: deterministic, no randomness — searches, fetches, reports
  every catalog issue. Used by the correctness tests.
- `SeededStub(seed)` / `DomainSeededStub(domain, seed)`: `random.Random(seed)`
  varies which findings get included/dropped, how many passages get
  fetched, verdict jitter (revise ↔ reject only — never "accept" with highs
  present), and token counts. Same seed → identical run; seeds 0..4 give
  honest, reproducible variance. No unseeded randomness anywhere.
- All stubs cite only passages they fetched, with verbatim catalog quotes,
  so variance is in *coverage*, never in citation honesty.

## Measurement

`evaluate.py` runs 5 seeded runs per pattern, aggregates, prints the
comparison table, and **generates** `docs/adr.md` from the numbers. Metric
definitions (shared with the tests via `common.py`):

- **task success**: schema-valid Review AND every finding cited.
- **tool accuracy**: fraction of successful get_passage-family calls whose
  passage ends up cited (1.0 when a run made none — vacuous).
- **unsupported claims**: findings with a citation violation.
- **tool calls / tokens / latency**: per-run totals; variance is population
  stddev across the 5 seeds, reported not hidden.

Result: 100% task success and 100% sane verdicts everywhere; B costs ~2.0x
A's tokens (two specialist runs + merge); C matches A's calls at ~0.4x the
tokens (stubbed single-step retrieval) but carries graph machinery. The ADR
names **Pattern A** — the simplest pattern that passes, per the plan's
prior that multi-agent is not the default.

## Honest caveats

- The stubs are cooperative quoters, so unsupported-claims is 0.00
  everywhere; the metric is real (unit tests prove `validate_review`
  catches fabrications) but unstressed by these runs.
- Pattern C's token advantage over A is a stub artifact (one retrieval
  step vs three agent turns), not a claim about real models.
- Latencies are stub-local; the ADR treats them as relative. Latency
  figures are excluded from the ADR's verbatim-checked key figures for the
  same reason — wall-clock time cannot reproduce bit-for-bit.
- The seeded proposal always contains high-severity issues, so "verdict
  sane" is exercised only on the revise/reject side; an all-clean proposal
  (→ accept) is not in the measured set.

## Test report

22 tests, all passing:

```
PYTHONPATH=src:../lab-02/src:../lab-03/src .venv/bin/python -m pytest tests -q
22 passed in 0.16s
```

Coverage: proposal loading + word count; catalog quotes verbatim;
`verdict_for` rules; validator catches fabricated quotes and
accept-with-highs; per-pattern oracle correctness (schema-valid, fully
cited, sane verdict); loop rejects unknown tools; tool budget enforced;
pattern B tool isolation (cross-domain call → `unknown_tool`, findings stay
in-domain); typed handoffs + deterministic routing; merge dedupe/ordering;
pattern C happy path (`validate → extract → assess → review → publish`);
conflict → human review (never publishes); empty question → clarify;
conflict detector semantics; per-seed determinism + cross-seed variance;
tool-accuracy definition (including the vacuous and failed-call cases);
measurement harness aggregates with stddev; ADR generated and consistent
(winner + every key figure recomputed in-test and matched verbatim);
README "What done means" checklist present.
