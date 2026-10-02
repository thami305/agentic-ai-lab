# Lab 7 — Local MCP server (briefs, case search, discovery prompt)

Week 7 of the Agentic AI field plan. A local MCP server built with the
official Python MCP SDK, exposing exactly three capabilities with
deterministic, test-driven controls: JSON-schema arg validation,
allow-listed resource ids, read-only defaults, an explicit error taxonomy,
secret-redacting logs with per-request UUIDs, and per-capability
authorization enforced server-side.

Teaching model: the model proposes, deterministic code decides — here the
"model" is any MCP client, and the server decides what runs.

## Quickstart

```bash
cd agentic-ai-lab/lab-07
python3 -m venv .venv && .venv/bin/pip install -q "mcp==2.2.0" pydantic pytest

# run the 21 acceptance tests (no network, no API key; server + clients in-process)
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

Pinned versions (recorded per the plan): **mcp==2.2.0**, pydantic==2.13.5,
pytest==9.1.1, anyio==4.15.1 (ships with mcp), Python 3.12.3.

## Layout

```
lab-07/
  src/lab07/
    __init__.py        # package entry: build_server
    server.py          # MCPServer("lab7-briefs"): 1 resource + 1 tool + 1 prompt,
                       #   request ids, validation, authz, _test_delay_s test hook
    errors.py          # explicit error taxonomy -> JSON-RPC codes
    auth.py            # role contextvar + require_role()
    logging_utils.py   # request-id + secret-redacting logging filters
  data/
    briefs.json        # client briefs for acme / globex / initech
                       #   (globex holds the malicious-resource fixture)
    cases.json         # 8 synthetic cases for search_cases
  tests/
    helpers.py         # shared: SDK session helper, raw JSON-RPC client,
                       #   log capture, untrusted-data consumer
    test_client1_session.py  # 17 tests via high-level ClientSession
    test_client2_raw.py      # 4 tests via hand-rolled JSON-RPC 2.0 client
  docs/architecture.md # design notes, caveats, test report
  README.md            # this file
```

## The three capabilities

| Capability | Name | Contract |
|---|---|---|
| Resource | `brief://{client_id}` | read-only brief text; ids allow-listed to `acme`, `globex`, `initech`; requires role `viewer` |
| Tool | `search_cases(query: str, limit: int = 5)` | keyword search over `data/cases.json`; query ≤ 200 chars, 1 ≤ limit ≤ 50; requires role `analyst` |
| Prompt | `discovery_interview(client_name: str)` | reusable discovery-interview template; no role requirement |

Error taxonomy (clients see these as JSON-RPC error codes): `invalid_args`
(-32001), `unauthorized` (-32002), `not_found` (-32003), `oversized_input`
(-32004), `path_traversal` (-32005).

## What "done" means (from the plan)

- [x] Server exposes exactly the three spec'd capabilities (test_01 discovery, both clients)
- [x] Read-only brief resource, allow-listed ids only (tests 03, 09)
- [x] `search_cases` tool with JSON-schema args (tests 01, 02)
- [x] Discovery-interview prompt with `client_name` arg (tests 01, 04)
- [x] JSON-schema arg validation; invalid args rejected (tests 05, 06)
- [x] Allow-listed resource paths; path traversal rejected (test_08, raw test_04)
- [x] Read-only defaults: no write tools exist (test_12)
- [x] Explicit error types; clients see codes (tests 06–11)
- [x] Logs with secrets redacted (test_15)
- [x] Request IDs on every call, unique per call (test_14)
- [x] Per-tool authorization server-side; unauthorized → explicit error, no data (tests 10, 11)
- [x] Malicious resource returned verbatim + wrapped in `[UNTRUSTED RESOURCE DATA]`; instruction never acted on (test_13)
- [x] Oversized input rejected (test_07)
- [x] Tool timeout bounded; server reusable after (test_16)
- [x] Client disconnect mid-call; cleanup bounded; server reusable (test_17)
- [x] Two different in-process clients against the same server (test_client1_session.py, test_client2_raw.py)
- [x] `PYTHONPATH=src .venv/bin/python -m pytest tests -q` green: **21 passed**
- [x] mcp pinned to 2.2.0 and recorded here
