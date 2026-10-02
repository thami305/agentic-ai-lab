# Memory Decision Record — Lab 06

*One page. Effective: 2026-10-02. Owner: the consulting practice.*

## What is stored
Small, explicit user-stated facts: `{key, value, provenance, timestamp,
confidence, scope, expiry}`. A fact enters memory **only** when the user says
something matching an explicit remember statement (e.g. "remember that acme:
prefers Tuesday deploys"). History of superseded values is kept alongside the
entry while it is live.

## Why
So the assistant can recall client preferences and operating facts across
sessions without re-asking, while making every write traceable (who said it,
when) and every read time-bounded (expiry). No implicit learning: conversation
content is never promoted to memory on its own.

## Where
A single JSON file per store (`data/memory.json` by default; tests use
`tmp_path`). Format: `{key: entry_dict}`. Plaintext on the lab VM's disk —
no encryption at rest in this lab build.

## How long (TTL policy + decay)
- Every write sets `expiry = now + ttl_seconds` (default 3600s; callers choose).
- Reads require `now < expiry`; at or past expiry the fact is treated as gone
  (decay is lazy — it happens at read time, no sweeper).
- Expired entries are excluded from `list_keys()` and reads. There is no
  automatic purge of expired entries from the file in this build.

## Who can access (scope namespacing)
- Every entry belongs to exactly one `scope` (client namespace, e.g. `acme`).
- `get()` and `list_keys()` require an exact scope match. There is no
  cross-scope read path; client A's facts are never returned under client B's
  namespace. Scope strings are case-sensitive and must match exactly.

## How it is corrected (contradictory update rule)
If a key is re-remembered while live, the newer value wins. The old
`{value, provenance, timestamp}` moves into the entry's `history` and the new
provenance is **appended** — both provenances are logged, so corrections are
auditable rather than silent overwrites.

## How it is deleted (tombstone + verification)
`delete(key, scope)` writes a tombstone: the key, scope, provenance log
(without values), and `deleted_at` are kept; the `value` and all history values
are scrubbed from the file. Afterwards `get()` returns `None`. Deletion is
verifiable: `verify_absent(key, value)` scans the raw file bytes and returns
`True` only if the value appears nowhere. A later explicit remember clears the
tombstone and the key is usable again (scrubbed history is not resurrected).

## What is NEVER stored
1. **Sensitive patterns** — values matching `password[:=]...`, SSN
   `\d{3}-\d{2}-\d{4}`, or 16-digit card shapes are rejected with
   `SensitiveContentError` and nothing is persisted (heuristic regexes; see
   architecture.md caveats).
2. **Untrusted content** — retrieved documents, tool outputs, and any other
   non-user text go through `ingest_document()`, which by construction cannot
   write. An injected "remember this: ..." inside a document is data, never an
   instruction.
3. **Non-statements** — questions ("do you remember my birthday?"), prose, and
   anything that is not the full-message imperative remember form write
   nothing.
