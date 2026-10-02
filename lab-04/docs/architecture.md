# Lab 4 architecture: checkpoint, interrupt, resume

## Why checkpoint after every node

A crash can land anywhere: in a model node, in a router, between nodes. The
only recovery story that survives all of those is "the last fully completed
node is on disk". `run_persistent` replicates lab03 `Graph.run`'s loop and
calls `store.save(run_id, state, next_node=<router result>, status="running")`
after each successful node. If `node.fn` raises, the exception propagates and
the checkpoint from the previous node is already durable: the crash never
leaves a half-written node state behind, because the save only happens after
the node (and its router) finished. `next_node` records exactly where to
continue, so `resume_run` just re-enters the same loop at that node.

The checkpoint serializes the whole `BriefState`: packet and brief via their
pydantic `model_dump()`, everything else is plain JSON. On load the state is
rebuilt field by field, so a resumed run sees identical passages, brief,
path, and counters.

## Why the interrupt is a node replacement

The approval pause is modeled as a graph node, not as special-case runner
logic. `build_interrupt_graph` builds lab03's graph, wraps the validate
router so a `"publish"` routing decision lands on `"await_approval"`, and
deletes the old publish node so no router can reach it by accident. The
runner treats it like any terminal node and saves the checkpoint with
`status="awaiting_approval"`. This keeps one code path for checkpointing
(every terminal node saves; only the status differs) and makes the pause
visible in `state.path` like everything else.

The human decision is applied by `resume(run_id, decision, ...)` outside the
graph loop: approve marks `publish` and records the side effect, reject marks
`review`, abandon marks `stop`. Edit-and-approve re-validates the edited
brief with lab02's `validate_brief` before replacing `state.brief`; an
invalid edit raises and the run stays `awaiting_approval` with the
checkpoint untouched.

## Idempotency via the side-effect log

Duplicate resume is safe because of two ordered guards:

1. Once a decision is applied, the checkpoint is rewritten with
   `status="decided"` and the decision recorded in it. A second `resume`
   call sees `"decided"` and returns the already-logged decision before
   touching anything: first decision wins.
2. The publish side effect is appended to `side_effects.jsonl` only if no
   record with that `run_id` exists yet. Even if the guard in (1) were
   bypassed, the side effect could not be applied twice.

Every decision is also appended to `decisions.jsonl` as
`{run_id, decision, at, edited}`, exactly once per decided run: the append
happens after the side-effect guard and before the status flip, inside the
same non-`"decided"` branch.

## Honest caveats

- The JSON file store is single-writer with no locking. Two processes writing
  the same run_id concurrently can interleave or clobber each other. Fine
  for the lab; a real deployment wants atomic writes plus a lock or a proper
  store (SQLite, Postgres).
- The TTL clock is wall-clock (`time.time` by default). Tests inject a fixed
  clock for determinism, but production TTLs are vulnerable to clock skew
  and NTP jumps; a monotonic clock cannot be used across processes.
- Crash-during-save is not handled: if the process dies mid-`write_text`,
  the checkpoint file can be truncated. Atomic rename (write temp file,
  then rename) is the obvious next step and is left as future work.
- `resume_run` restarts the step counter at zero, so a resumed run gets a
  fresh `max_steps` budget rather than the remainder of the original.
- The interrupt only guards the publish path. Terminals reached through
  `clarify`, `review`, or `stop` finish without human approval by design.

## Test report

22 tests, all deterministic, no network. Coverage: checkpoint file written
after run start; full state round-trip; approve/reject/abandon/edit paths;
valid and invalid human edits; decision logging format; duplicate resume
idempotency (one decision record, one side-effect record, second decision
does not override the first); unknown run_id; resume while still running;
resume of a finished run; TTL expiry fails closed with nothing published;
TTL boundary just inside the limit loads fine; crash keeps the last
completed checkpoint (status/next_node/path); crash then resume from a fresh
store and graph preserves passage evidence; CountingPolicy proves retrieval
is not re-executed on resume (counter stays 1); the review branch bypasses
the approval interrupt.

22 passed in 0.66s
