"""Lab 1 CLI.

Examples:
    python -m lab01.run --seed
    python -m lab01.run --demo acme
    python -m lab01.run --demo globex
    python -m lab01.run --model openai "What is Initech's win rate?"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab01.agent import Agent, AgentConfig  # noqa: E402
from lab01.db import seed  # noqa: E402
from lab01.models import (AnthropicBackend, OpenAIBackend, ScriptedStub,  # noqa: E402
                          calls, decline, final_rec, tc)
from lab01.tools import build_registry  # noqa: E402


def _demo_script(name: str):
    if name == "acme":
        return ("What is Acme's weighted pipeline, and what should we do?", [
            calls(tc("calculate_metric", {"metric": "weighted_pipeline", "client_id": "acme"})),
            final_rec(client_id="acme", metric_name="weighted_pipeline", metric_value=256000.0,
                      recommendation="hold",
                      rationale="Acme's weighted open pipeline is $256,000 across 3 deals, "
                                "inside the hold band. No action needed yet.",
                      confidence="high", data_sources=["calculate_metric"]),
        ])
    if name == "globex":
        return ("Should we expand with Globex?", [
            calls(tc("list_deals", {"client_id": "globex"})),
            calls(tc("calculate_metric", {"metric": "weighted_pipeline", "client_id": "globex"})),
            final_rec(client_id="globex", metric_name="weighted_pipeline", metric_value=337500.0,
                      recommendation="expand",
                      rationale="Globex weighted pipeline is $337,500 across 3 open deals with "
                                "strong closed-won history. Data supports expansion.",
                      confidence="high", data_sources=["list_deals", "calculate_metric"]),
        ])
    raise ValueError(f"unknown demo '{name}'")


def _result_to_json(result) -> dict:
    out = {"status": result.status, "turns": result.turns,
           "total_tokens": result.total_tokens,
           "latency_s": round(result.latency_s, 3),
           "trace": [{"tool": t.name, "ok": t.ok, "cached": t.cached,
                      "attempts": t.attempts, "error": t.error,
                      "latency_s": round(t.latency_s, 3)} for t in result.tool_trace]}
    if result.recommendation is not None:
        out["recommendation"] = result.recommendation.model_dump()
    if result.decline is not None:
        out["decline"] = result.decline.model_dump()
    if result.error is not None:
        out["error"] = result.error
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Lab 1: deterministic tool-using assistant")
    parser.add_argument("request", nargs="?", help="the business question to answer")
    parser.add_argument("--model", choices=["stub", "openai", "anthropic"], default="stub")
    parser.add_argument("--db", default="data/pipeline.db")
    parser.add_argument("--seed", action="store_true", help="(re)create the demo database")
    parser.add_argument("--demo", choices=["acme", "globex"],
                        help="run a canned deterministic demo (uses the stub)")
    parser.add_argument("--max-turns", type=int, default=8)
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.seed or not db_path.exists():
        seed(db_path)
        print(f"seeded {db_path}", file=sys.stderr)

    registry = build_registry(db_path)

    if args.demo:
        request, script = _demo_script(args.demo)
        backend: object = ScriptedStub(script)
    elif args.model == "openai":
        request, backend = args.request, OpenAIBackend()
    elif args.model == "anthropic":
        request, backend = args.request, AnthropicBackend()
    else:
        parser.error("with --model stub, pass --demo (the stub needs a script; see tests/)")

    if not request:
        parser.error("provide a request, e.g. \"What is Acme's weighted pipeline?\"")

    agent = Agent(backend, registry, AgentConfig(max_turns=args.max_turns))  # type: ignore[arg-type]
    result = agent.run(request)
    print(json.dumps(_result_to_json(result), indent=2))


if __name__ == "__main__":
    main()
