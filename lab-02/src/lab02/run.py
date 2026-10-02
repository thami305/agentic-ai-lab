"""Lab 2 CLI.

Deterministic demos (no API key needed):

    PYTHONPATH=src python -m lab02.run brief --mode tool "How utilized is Northwind's current warehouse?"
    PYTHONPATH=src python -m lab02.run brief --mode prompt "How utilized is Northwind's current warehouse?"
    PYTHONPATH=src python -m lab02.run compare

With a real model (bring a key via your secure vault, never in a file):

    pip install openai   # or: pip install anthropic
    export OPENAI_API_KEY=...
    export LAB_MODEL=<current-model-id>
    PYTHONPATH=src python -m lab02.run brief --model openai --mode tool "..."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab02.agent import Agent, PROMPT_ONLY_SYSTEM  # noqa: E402
from lab02.evaluate import aggregate, comparison_table, load_questions, run_eval  # noqa: E402
from lab02.models import (AnthropicBackend, OpenAIBackend, OracleStub,  # noqa: E402
                          PromptOnlyStub)
from lab02.packet import load_packet  # noqa: E402
from lab02.tools import ToolRegistry, build_registry  # noqa: E402


def make_agent(mode: str, model: str | None, packet):
    if model == "openai":
        backend = OpenAIBackend()
    elif model == "anthropic":
        backend = AnthropicBackend()
    elif mode == "tool":
        backend = OracleStub()
    else:
        backend = PromptOnlyStub()
    registry = build_registry(packet) if mode == "tool" else ToolRegistry()
    system = PROMPT_ONLY_SYSTEM if mode == "prompt" else None
    kwargs = {"system_prompt": system} if system else {}
    return Agent(backend, registry, packet, **kwargs)  # type: ignore[arg-type]


def cmd_brief(args) -> int:
    packet = load_packet()
    agent = make_agent(args.mode, args.model, packet)
    result = agent.run(args.question)
    print(f"status: {result.status}")
    print(f"turns: {result.turns}  tool_calls: {result.tool_calls_made}  "
          f"tokens: {result.total_tokens}  latency_s: {result.latency_s:.3f}")
    if result.brief is not None:
        print(result.brief.model_dump_json(indent=2))
    if result.decline is not None:
        print(result.decline.model_dump_json(indent=2))
    if result.error is not None:
        print(f"error: {result.error}")
        return 1
    return 0


def cmd_compare(args) -> int:
    del args
    packet = load_packet()
    questions = load_questions()
    scored = run_eval(packet, questions)
    agg = aggregate(scored)
    print(f"{len(questions)} questions x 2 modes (deterministic stubs)\n")
    print(comparison_table(agg))
    print("\nper-question groundedness (tool vs prompt):")
    for q in questions:
        t = next(s for s in scored if s.question_id == q.id and s.mode == "tool")
        p = next(s for s in scored if s.question_id == q.id and s.mode == "prompt")
        print(f"  {q.id} [{q.expect:>7}] tool={t.groundedness:.2f} "
              f"prompt={p.groundedness:.2f}  tool_complete={t.completeness:.2f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lab02.run", description="Lab 2: evidence-grounded research brief")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("brief", help="answer one question")
    b.add_argument("question")
    b.add_argument("--mode", choices=["tool", "prompt"], default="tool")
    b.add_argument("--model", choices=["openai", "anthropic"], default=None)
    b.set_defaults(fn=cmd_brief)

    c = sub.add_parser("compare", help="prompt-only vs tool-using on 15 questions")
    c.set_defaults(fn=cmd_compare)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
