# Lab 3 architecture

## Why a graph

Lab 2's agent was a loop: correct, but the control flow lived in one `run()`
method and the branches were implicit. Lab 3 makes the workflow explicit —
the plan's requirement is that *a test can assert the path taken*. So the
pipeline becomes named nodes over typed shared state, with conditional edges
as pure functions.

The runtime (`graph.py`) is deliberately minimal (~60 lines): nodes declare a
kind, edges are router functions, the path is recorded on the state, steps
are capped against cycles, and a router naming a missing node fails loudly.
No framework dependency — the point of the lab is to understand the
mechanics, not to learn an API.

## The deterministic / model split

Each node declares its kind, and the tests assert the declaration:

- **Deterministic** (pure code, no model): `validate_input`, `assess`,
  `validate`. Input checks, conflict detection, citation post-validation.
- **Model-driven**: `retrieve`, `synthesize`. In production these call a real
  backend; here they call a `Policy`. The default `OraclePolicy` is the Lab 2
  oracle ported over — deterministic, so the graph tests need no API key.

The discipline from Labs 1–2 carries over unchanged: the model proposes
(passages, brief JSON), deterministic code decides (routing, validation,
terminal states).

## Conflict detection

`detect_conflict` is intentionally mechanical, not semantic: two retrieved
passages sharing ≥2 keywords, where one carries a revision marker (`revised`,
`superseding`, …), route to `review` with both passages quoted in the reason.
The packet ships one deliberate conflict pair — the original 14-month
break-even estimate versus the revised 22-month note. A real system would use
an NLI model or a human here; the lab's lesson is *where the branch lives*,
not how clever the detector is.

## Bounded retries and the graceful stop

`retrieve` retries failed retrieval up to `MAX_RETRIEVAL_RETRIES` (2), then
routes to `stop` — a terminal state with the failure recorded, instead of
answering without evidence or crashing. `FlakyPolicy` (fails N times, then
succeeds) exercises both sides: fail twice → publish with `retrieval_retries`
recorded; fail always → `stop`.

## Reuse, not rewrite

Lab 3 imports Lab 2 (`PYTHONPATH=src:../lab-02/src`): the packet loader, the
keyword retrieval, and the post-validator are shared. What changed is the
*shape* — loop to graph — not the guarantees. The packet gained exactly one
passage (the revised finance note); Lab 2's files are untouched.

## Test report

19 acceptance tests, all deterministic:

- 1–7: branch paths (publish, clarify ×2, review ×2, stop, retry-then-publish)
- 8–9: state inspection, all four terminals reachable
- 10–15: router unit tests + conflict detector unit tests
- 16–19: node-kind declarations, loud failures (unknown entry, unknown node,
  terminal without state)

```
19 passed in 0.06s
```
