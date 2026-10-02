# Lab 2 — Evidence-grounded research brief

Week 2 of the Agentic AI field plan. An agent that answers a business question
from a curated document packet, with every factual claim mapped to verbatim
evidence. Includes a head-to-head evaluation: prompt-only versus tool-using on
the same 15 questions.

## Quickstart

```bash
cd agentic-ai-lab/lab-02
python3 -m venv .venv && .venv/bin/pip install -q pydantic pytest

# one brief, tool-using (deterministic, no API key needed)
PYTHONPATH=src .venv/bin/python -m lab02.run brief --mode tool \
  "How utilized is Northwind's current warehouse?"

# the same question, prompt-only (no tools) — watch the citations fail
PYTHONPATH=src .venv/bin/python -m lab02.run brief --mode prompt \
  "How utilized is Northwind's current warehouse?"

# the full comparison: 15 questions x 2 modes
PYTHONPATH=src .venv/bin/python -m lab02.run compare

# run the 21 acceptance tests
PYTHONPATH=src .venv/bin/python -m pytest tests -q
```

## Using a real model

```bash
pip install openai   # or: pip install anthropic
export OPENAI_API_KEY=...        # via your secure vault, never in a file
export LAB_MODEL=<current-model-id>
PYTHONPATH=src .venv/bin/python -m lab02.run brief --model openai --mode tool \
  "What do customers say about delivery speed?"
```

The model must return its final answer as JSON matching the `ResearchBrief`
(or `Decline`) schema; anything else fails the run loudly. The deterministic
post-validator then checks every citation against the packet.

## Layout

```
lab-02/
  src/lab02/
    agent.py     # control loop: allow-list, validation, two budgets
                 #   (max_turns, max_tool_calls), caching, tracing
    models.py    # ScriptedStub (unit tests), OracleStub (deterministic
                 #   tool-using policy), PromptOnlyStub (no tools, fabricated
                 #   citations), OpenAI/Anthropic adapters
    tools.py     # read-only packet tools: list_sources, search_docs, get_passage
    schemas.py   # Pydantic contracts: Packet, Evidence, Claim, ResearchBrief
    validate.py  # deterministic post-validation of every brief
    packet.py    # packet loader (the only ground truth the agent may cite)
    evaluate.py  # prompt-only vs tool-using harness + five-dimension scoring
    run.py       # CLI: brief | compare
  data/
    packet.json          # 5 sources, 19 passages (one carries an injection payload)
    eval_questions.json  # 15 questions: 10 answerable, 3 partial, 2 unanswerable
  tests/test_lab02.py    # 21 acceptance cases
  docs/architecture.md   # design notes + evaluation results
```

## What "done" means (from the plan)

- [x] Every factual claim maps to supplied evidence (tests 1–5, 20)
- [x] Citations survive formatting: quotes must be verbatim substrings (tests 4, 5)
- [x] Unsupported questions are flagged, not answered (tests 7, 21)
- [x] The structured result parses in every test (tests 13, 18)
- [x] Prompt-only vs tool-using compared on 15 questions across completeness,
      groundedness, format validity, cost, latency (`run compare`, tests 19–21)
- [x] Model and tool budgets enforced (tests 8, 9)
- [ ] Two-minute demo recording — record when walking through the demos
