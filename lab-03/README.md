# Lab 3 — Orchestration and state

Week 3 of the Agentic AI field plan. Lab 2's pipeline rebuilt as an explicit
graph: named nodes, typed shared state, conditional routing, bounded retries,
and a declared split between deterministic and model-driven steps.

## Quickstart

```bash
cd agentic-ai-lab/lab-03
python3 -m venv .venv && .venv/bin/pip install -q pydantic pytest
export PYTHONPATH=src:../lab-02/src   # lab-03 reuses lab-02's packet + validator

# happy path: validate_input -> retrieve -> assess -> synthesize -> validate -> publish
.venv/bin/python -m lab03.run "How utilized is Northwind's current warehouse?"

# conflicting evidence -> review
.venv/bin/python -m lab03.run "When does finance expect the second site to break even?"

# missing input -> clarify
.venv/bin/python -m lab03.run ""

# run the 19 acceptance tests
.venv/bin/python -m pytest tests -q
```

## Layout

```
lab-03/
  src/lab03/
    graph.py     # minimal runtime: nodes, conditional edges, path recording,
                 #   step cap, loud failures
    state.py     # BriefState: the typed, inspectable record of the run
    nodes.py     # the pipeline as named nodes + pure router functions
    policies.py  # model-driven policies: OraclePolicy (deterministic),
                 #   FlakyPolicy and BadBriefPolicy (failure injection)
    run.py       # CLI: prints path taken, terminal state, brief or reason
  data/packet.json       # lab-02's packet + a revised finance note (conflict pair)
  tests/test_lab03.py    # 19 acceptance cases
  docs/architecture.md   # design notes
```

## Branches

| Condition | Path | Terminal |
|---|---|---|
| Empty question | validate_input → clarify | clarify |
| No passages retrieved | … → assess → clarify | clarify |
| Conflicting evidence | … → assess → review | review |
| Brief fails post-validation | … → validate → review | review |
| Retrieval fails 3x | retrieve → stop | stop (graceful) |
| All checks pass | … → validate → publish | publish |

## What "done" means (from the plan)

- [x] Lab 2 converted to named nodes with typed shared state
- [x] Conditional routing; bounded retries; deterministic and model-driven
      steps declared per node
- [x] A test can assert the path taken (`state.path`)
- [x] State mutations are inspectable (passages, brief, retries, violations)
- [x] Each branch reaches an intentional terminal state (clarify, review,
      publish, stop — all four reachable in tests)
- [ ] Two-minute demo recording — record when walking through the demos
