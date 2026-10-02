# Agentic AI Lab

Hands-on lab series for the Agentic AI field plan — deterministic,
test-driven agent engineering. Each lab is self-contained: its own code,
tests, docs, and virtualenv. No API key needed for the deterministic paths;
bring one via your secure vault for the live-model paths.

Teaching model: the model proposes, deterministic code decides.

## Labs

| Lab | Topic | Tests |
|-----|-------|-------|
| lab-01 | Deterministic tool-using assistant over a seeded SQLite client pipeline | 20 |
| lab-02 | Evidence-grounded research brief + prompt-only vs tool-using evaluation | 21 |
| lab-03 | Orchestration and state: Lab 2 as an explicit graph with conditional routing | 19 |
| lab-04 | Checkpoint, interrupt, resume: persistence + approval gate before publish | 22 |
| lab-05 | Retrieval-augmented adviser: 40-doc synthetic corpus, hybrid retrieval, eval | 20 |
| lab-06 | Memory with consent and decay: namespaced store, attack-tested | 20 |
| lab-07 | Local MCP server: 3 capabilities, 2 clients, redacted logs | 21 |
| lab-08 | One task, three orchestration patterns + architecture decision record | 22 |
| lab-09 | Golden set (50 cases) and trace-driven regression gate | 17 |
| lab-10 | Adversarial action harness: 10 attacks, all denied and audit-logged | 33 |
| lab-11 | Production-shaped service: API, job queue, idempotency, kill switch | 22 |
| lab-12 | Capstone: Client Operations Copilot, packaged with evals and runbook | 19 |

257 tests total, all deterministic, all passing.
