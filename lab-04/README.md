# Lab 4: Checkpoint, Interrupt, Resume

Takes the Lab 3 research graph and makes it durable: the full `BriefState`
is checkpointed to a JSON file after every node, the publish terminal is
replaced with an approval interrupt, and a crashed run can be resumed from
a fresh process. Side effects are applied at most once; stale checkpoints
fail closed.

## Quickstart

```bash
cd lab-04
python3 -m venv .venv
.venv/bin/pip install pydantic pytest

# run the tests
PYTHONPATH=src:../lab-03/src:../lab-02/src .venv/bin/python -m pytest tests -q

# run the end-to-end demo (crash -> resume -> approve -> publish)
PYTHONPATH=src:../lab-03/src:../lab-02/src .venv/bin/python -m lab04.run demo
```

## Layout

```
lab-04/
  src/lab04/
    checkpoint.py   CheckpointStore: JSON save/load per run_id, TTL with
                    injectable clock, decisions.jsonl + side_effects.jsonl
    runner.py       run_persistent (Graph.run loop + checkpoint after every
                    node), resume_run (fresh store + fresh graph, continue
                    from next_node)
    interrupt.py    build_interrupt_graph (publish terminal -> await_approval),
                    resume(run_id, decision, edited_brief=None)
    policies.py     CrashPolicy (raises in synthesize), CountingPolicy
                    (counts retrieve() executions)
    run.py          CLI demo
  tests/
    conftest.py     packet/store/paused fixtures
    test_lab04.py   22 deterministic tests, no network
  docs/
    architecture.md design notes, caveats, test report
  data/
    packet.json     document packet (copied from lab-03)
```

The demo writes its checkpoints to `data/demo-runs/`; tests use `tmp_path`
and leave nothing behind.

## What done means

- [x] Side effects never duplicated: the publish side effect is appended to
      `side_effects.jsonl` at most once per run_id; a duplicate resume
      returns the already-logged decision without touching it again.
- [x] The approval decision is logged: every decision is appended to
      `decisions.jsonl` as `{run_id, decision, at, edited}`.
- [x] A resumed run preserves evidence and context: the checkpoint holds the
      full BriefState (passages, brief, path, counters); resume continues
      from `next_node` without re-executing completed tools.
- [x] A stale run fails closed: loading a checkpoint older than the TTL
      raises `StaleCheckpointError` on both `load` and `resume`; nothing is
      published and nothing is logged.
- [ ] Two-minute demo recording: record when walking through the demos.
      (Manual step, not yet done.)
