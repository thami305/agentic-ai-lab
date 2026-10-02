# Lab 2 architecture

## The idea

Lab 1 proved the loop: the model proposes, deterministic code decides. Lab 2
applies the same doctrine to a harder problem — a research brief where the
failure mode isn't a wrong number but an ungrounded claim. The core mechanism
is the **deterministic post-validator** (`validate.py`): after the model
produces a `ResearchBrief`, code checks every citation against the packet
before the brief is allowed to ship.

Three checks, all mechanical:

1. Each evidence entry names a real `source_id` and `passage_id`.
2. Each quote is a verbatim substring of the cited passage (whitespace
   normalized). A paraphrase, a changed number, or an invented sentence fails.
3. Every claim carries at least one evidence entry. Unsupported material must
   live in `open_questions` — never in `claims`.

## The two modes

**Tool-using** (`OracleStub` in tests): searches the packet for the question's
keywords, fetches the top passages, and builds claims from their verbatim
first sentences. Deterministic — the same question always yields the same
brief, and validation always passes.

**Prompt-only** (`PromptOnlyStub`): no tools. Produces a confident brief citing
real source ids with fabricated quotes. Deterministic — and deterministically
caught: every quote fails check 2.

This is deliberately adversarial. The prompt-only stub models the exact
failure mode the lab exists to prevent: fluent, well-formatted, fully cited —
and entirely invented.

## Evaluation results (deterministic stubs)

15 questions: 10 answerable, 3 partially answerable, 2 unanswerable.

```
mode      complete  grounded  format  tokens  latency_s  declines
prompt       0.000     0.000   0.000   10500      0.000         0
tool         0.850     1.000   1.000   47300      0.023         2
```

Reading the table:

- **Groundedness** is the headline: 1.000 vs 0.000. The tool-using brief's
  claims all cite verbatim; the prompt-only brief's citations are all
  fabricated.
- **Format validity**: the tool path produced a valid brief (or a proper
  decline) on all 15; prompt-only produced zero valid briefs.
- **Declines**: the tool path declined both unanswerable questions (CEO
  compensation, Q4 marketing) instead of inventing answers. Prompt-only
  answered both — confidently and wrongly.
- **Cost**: tool-using costs ~4.5x the tokens (retrieval turns aren't free).
  That is the honest price of groundedness, and the number a client
  conversation should start from.
- **Completeness** 0.850 for tool mode: q11 ("should we open the warehouse?")
  covers 3 of 4 key points and leaves the decision open; q12 ("which
  location?") correctly reports the packet names no locations.

## Injection handling

`DOC-COMP-3` carries an instruction payload ("Ignore all previous
instructions..."). The policy, matching Lab 1:

- Tool output is untrusted data. The agent may **quote** it as evidence (it is
  real text in the packet) but must never **adopt** it as reasoning.
- Structurally, `assumptions` and `open_questions` are never derived from
  passage prose, so an injected directive cannot leak into the agent's own
  conclusions. Test 15 retrieves the injection passage and asserts exactly
  this.

Residual risk, stated plainly: quoting is not following, but a human reader
could still be misled by a quoted directive. In a client-facing product, the
brief renderer should visually distinguish quoted evidence from the agent's
own text. That is a presentation-layer control, out of scope for this lab.

## Budgets

Two independent budgets, both fail-loud:

- `max_turns` (default 8): model turns per run.
- `max_tool_calls` (default 12): tool executions per run, cached or not.

Exceeding either ends the run as an error, never as a silent partial brief.

## Test report

21 acceptance tests, all deterministic, no API key required:

- 1–5: post-validation (valid brief passes; bad source, bad passage,
  fabricated quote, altered quote all fail)
- 6–14: agent loop (end-to-end brief, decline on unanswerable, both budgets,
  unknown tool rejected, bad args rejected, cache hits, invalid JSON fails
  loudly, model errors surface)
- 15: injection quoted as evidence at most, never adopted
- 16–18: prompt-only executes zero tools; its citations fail validation; it
  answers unanswerable questions instead of declining
- 19–21: eval assertions (tool groundedness > prompt; tool format-valid on
  all answerable/partial; decline behavior per mode)

```
21 passed in 0.11s
```
