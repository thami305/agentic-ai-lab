"""CLI: intake a JSON exception file, run the copilot, print the result.

Usage:
  python -m lab12.run data/demo_case.json --out out/
  python -m lab12.run data/demo_case.json --out out/ --policy-store data/policies.json
  python -m lab12.run case.json --out out/ --outage   # simulate policy-store outage

Prints the terminal state, risk, citations, and where the artifact and queue
were written. Exits 0 on resolved/queued_for_approval, 2 on
needs_clarification, 3 on degraded.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .copilot import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Client Operations Copilot")
    parser.add_argument("case", help="JSON file with the exception")
    parser.add_argument("--out", default="out",
                        help="directory for the incident artifact")
    parser.add_argument("--queue", default="",
                        help="approval queue JSON path (default: <out>/queue.json)")
    parser.add_argument("--policy-store", default="",
                        help="policies.json path (default: data/policies.json "
                             "next to the lab, or ../data via LAB12_DATA)")
    parser.add_argument("--outage", action="store_true",
                        help="simulate a policy-store outage")
    args = parser.parse_args(argv)

    base = os.path.dirname(os.path.abspath(__file__))
    policy_path = args.policy_store or os.environ.get(
        "LAB12_POLICY_STORE",
        os.path.join(base, "..", "..", "data", "policies.json"))
    out_dir = args.out
    queue_path = args.queue or os.path.join(out_dir, "queue.json")

    with open(args.case, encoding="utf-8") as f:
        raw = json.load(f)

    result = run(raw, policy_path, queue_path, out_dir, force_outage=args.outage)

    print(f"case:     {result.case_id}")
    print(f"terminal: {result.terminal}")
    print(f"risk:     {result.risk}" + (f" ({result.rule_name})" if result.rule_name else ""))
    print(f"reason:   {result.reason}")
    if result.injection_flagged:
        print("note:     description contained instruction-like text — "
              "quoted in the artifact, never followed")
    for c in result.citations:
        print(f"cite:     {c.policy_id} / {c.section}")
    for qid in result.queued_ids:
        print(f"queued:   {qid} (awaiting human approval — NOT executed)")
    print(f"artifact: {result.artifact_path}")
    print(f"queue:    {queue_path}")
    print(f"tokens:   {result.token_usage.get('total', 0)} (est.)")

    return {"resolved": 0, "queued_for_approval": 0,
            "needs_clarification": 2, "degraded": 3}[result.terminal]


if __name__ == "__main__":
    sys.exit(main())
