# Lab 10 — architecture notes

## What it is

An adversarial action harness: 10 attack cases run against a hardened
agent loop. The loop is lab-01's allow-list control loop extended with the
defenses a production agent needs before it is allowed to *do* things:
least-privilege roles, an HMAC-signed approval channel with a
shown-vs-actual gate, a consent gate for memory writes, per-run budgets,
namespace isolation, and a hash-chained audit log that records every
decision with a reason.

The threat model assumes the model itself is untrusted. The ScriptedStub
plays both the benign model (happy paths) and the compromised model
(attack scripts that issue the malicious calls). The loop — deterministic
code — is the defender. Teaching model, as always: the model proposes,
deterministic code decides.

## Defense layers, in execution order

For every tool call the loop runs these gates in order; the first failure
denies the call, logs the denial with a reason, and stops the run
fail-closed:

1. **Rate limit** — `RateLimiter(max_tool_calls)`: the (n+1)-th execution
   is denied before it starts.
2. **Allow-list** — `ToolRegistry.get(name)`; unknown names are rejected,
   never executed (attacks 4, 5).
3. **Least privilege** — `tool.roles` must include the caller's role.
   `export_client_list` is `{"admin"}` only (attacks 1, 3).
4. **Schema validation** — Pydantic `args_model(**args)` before execution,
   `extra="forbid"` everywhere. `client_id` must match
   `^[a-z0-9][a-z0-9_-]{0,63}$`, so `../../../etc/passwd` dies here
   (attack 2). There is deliberately no `consent` field on
   `WriteMemoryArgs`: consent is not a model-supplied argument.
5. **Namespace** — on the *validated* args: `client_id` must equal the
   run's namespace (attack 10, arg-level).
6. **Consent gate** — `write_memory` needs `ConsentStore.granted("memory")`.
   Default deny; only user code outside the conversation can grant
   (attack 6).
7. **Approval gate** — high-impact tools (`export_client_list`,
   `send_notification`) need an `Approval` from the `ApprovalChannel`.
   `ApprovalGate.verify` checks, in order: action match, payload-hash
   match, HMAC signature validity, and shown-text == canonical rendering
   of the actual payload (attacks 7, 9).
8. **Execution** — `ToolOutageError` aborts the run bounded; later scripted
   turns never execute, so there are no partial writes (attack 8).
9. **Output hygiene** — results are labeled `[UNTRUSTED DATA]` at the
   model boundary; instruction-like payloads are flagged
   (`attack_deflected: untrusted_instruction_ignored`) and treated as data
   only; `_ns` markers are scanned and foreign-client data denies the
   result fail-closed (attacks 4, 10).

Budgets are checked per turn as well: `SpendLimiter` aborts when tokens
exceed the cap, before any further tool runs.

## The signed approval channel

An approval is a frozen dataclass:
`{action, payload_hash, shown_text, signature}` where
`signature = HMAC(secret, action|payload_hash|shown_text)`.
The gate verifies four things, and the order matters:

- `action_mismatch` / `payload_hash_mismatch` catch payload substitution.
- `signature_invalid` catches attack 7: a "manager approved" message in
  conversation history carries no HMAC, so it can never verify. History
  is recorded in the audit as `untrusted_context_injected` — visible,
  never authoritative.
- `shown_text_mismatch` catches attack 9: the HMAC is *valid* (signed
  with the real secret, simulating a compromised UI), but the text the
  approver saw ("Send summary to client") differs from the canonical
  rendering of the payload that would execute
  (`export_client_list(client_id='acme', format='csv')`).

`canonical_render` sorts keys and uses `repr` for values, so there is
exactly one true rendering to compare against.

## The audit log

Append-only JSON lines: `{seq, ts, run_id, event, reason, tool, …,
prev_hash, hash}` with `hash = sha256(canonical_json(entry))`. No public
mutator exists; `entries()` returns copies. `verify_chain()` recomputes
every link — the tamper test edits a persisted line and the chain check
fails. Every `denied` event carries a non-empty `reason`; the
`run_aborted` event (attack 8) does too.

## Controls → tests

| Control | Test |
|---|---|
| Goal hijack denied by least privilege; export never executes | attack 1 |
| Path traversal rejected by schema before execution | attack 2, `test_schema_rejects_path_traversal_directly` |
| Analyst denied admin-only tool | attack 3 |
| Exploit string labeled untrusted, flagged, never followed | attack 4, `test_tool_output_labeled_untrusted_data` |
| Unknown `exec_python` fails closed | attacks 4, 5 |
| Memory write needs explicit consent (default deny); model cannot smuggle `consent` in args | attack 6, `test_consent_default_deny_then_grant`, `test_consent_cannot_be_smuggled_in_args` |
| Spoofed history approval rejected (no HMAC) | attack 7, `test_wrong_secret_rejected`, `test_missing_approval_rejected` |
| Outage aborts bounded; no writes past the abort point | attack 8 |
| Shown-vs-actual mismatch denied despite valid HMAC | attack 9, `test_shown_vs_actual_mismatch_rejected_despite_valid_hmac` |
| Cross-client `_ns` markers deny the result; B data never reaches the model | attack 10, `test_namespace_enforcer_finds_nested_markers`, `test_namespace_arg_mismatch_denied_before_execution` |
| Audit append-only; tamper detected | `test_audit_append_only_and_chain_verifies`, `test_audit_tamper_detected`, `test_audit_entries_are_copies` |
| Every denial in every attack has a reason; chain verifies | `test_every_attack_denial_has_a_reason` |
| Legit signed approval executes the high-impact tool | `test_legit_approval_passes_gate`, `test_legit_approval_executes_high_impact_tool` |
| Rate limit / spend limit enforced | `test_rate_limit_denies_over_limit_run`, `test_spend_limit_aborts_before_tools_run` |

## Honest caveats

- **The stub is both attacker and model.** The attacks prove the *loop*
  denies malicious calls; they say nothing about whether a real model
  would attempt them, or about prompt-level jailbreaks. Red-teaming a live
  model is a different lab.
- **The channel secret is a test constant** (`TEST_CHANNEL_SECRET`). In
  production it lives in a vault/HSM with rotation; anyone holding it can
  mint approvals. The lab's claim is about the *verification logic*, not
  secret management.
- **The instruction detector is a heuristic regex list**, not a security
  boundary. It exists to label and log (attack 4); the actual safety comes
  from the allow-list and the approval gate, which hold even when the
  detector misses.
- **No real sandboxing.** Unknown code-execution tools are denied by the
  allow-list (fail closed), which is the correct default — but if a
  *registered* tool executed untrusted code, this lab would not contain
  it. Lab-01's note stands: untrusted code belongs in a subprocess/sandbox.
- **Audit tamper-evidence is local.** The hash chain detects edits after
  the fact; it does not prevent them. Forward-secure logging (write to
  append-only remote storage) is the production answer.
- **Single-process, in-memory side effects.** `SideEffectLog` and
  `MemoryStore` are test doubles, not a real ledger — the "no partial
  writes" claim is about the loop stopping, not about distributed
  transactions.

## Test report

`PYTHONPATH=src .venv/bin/python -m pytest tests -q` — **33/33 passing**
(11 attack tests: 10 cases + case-count sanity; 22 defense unit tests).
See `test-report.txt` for the full run. CLI: `python -m lab10.run --all`
→ 10/10 attacks denied, exit 0.
