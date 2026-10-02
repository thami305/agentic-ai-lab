"""Rehearsal runner: run every case in data/rehearsal_cases.json and check
the terminal state and risk against expectations.

Usage:
  python -m lab12.eval data/rehearsal_cases.json [--out /tmp/lab12-eval]

Prints a per-case table and exits 0 iff every case matches. The table is the
raw material for docs/eval-report.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from . import actions
from .approvals import ApprovalQueue
from .copilot import CopilotResult, run_case
from .policies import PolicyStore, PolicyStoreError


def evaluate(cases: list[dict], policy_path: str, workdir: str,
             verbose: bool = True) -> list[dict]:
    """Run all cases. Each case is isolated: fresh queue, fresh audit trail.
    Returns a list of per-case result dicts."""
    results = []
    for case in cases:
        out_dir = os.path.join(workdir, case["id"])
        os.makedirs(out_dir, exist_ok=True)
        queue_path = os.path.join(out_dir, "queue.json")

        actions.EXECUTED_AUDIT.clear()
        outcome: CopilotResult
        try:
            if case.get("outage"):
                store = PolicyStore.load(policy_path, force_down=True)
            else:
                store = PolicyStore.load(policy_path)
        except PolicyStoreError as e:
            from .copilot import CopilotResult as CR, _usage, _write_artifact, estimate_tokens
            raw = case["input"]
            os.makedirs(out_dir, exist_ok=True)
            outcome = CR(case_id=str(raw.get("id") or "unknown"),
                         terminal="degraded", risk="unclassified",
                         reason=f"Policy store unavailable — {e}.",
                         token_usage=_usage(intake=estimate_tokens(str(raw))))
            outcome.artifact_path = _write_artifact(
                outcome, raw, out_dir,
                next_steps=["Restore the policy store, then re-run this case."],
                description=str(raw.get("description") or "(none provided)"))
        else:
            queue = ApprovalQueue(queue_path)
            outcome = run_case(case["input"], store, queue, out_dir)

        terminal_ok = outcome.terminal == case["expected_terminal"]
        risk_ok = (case.get("expected_risk") in (None, "")
                   or outcome.risk == case["expected_risk"])
        exec_ok = len(actions.EXECUTED_AUDIT) == 0  # nothing may ever execute
        passed = terminal_ok and risk_ok and exec_ok
        results.append({
            "id": case["id"],
            "expected_terminal": case["expected_terminal"],
            "actual_terminal": outcome.terminal,
            "expected_risk": case.get("expected_risk") or "-",
            "actual_risk": outcome.risk,
            "executed_actions": len(actions.EXECUTED_AUDIT),
            "pass": passed,
        })
        if verbose:
            mark = "PASS" if passed else "FAIL"
            print(f"[{mark}] {case['id']:32s} "
                  f"terminal={outcome.terminal:20s} risk={outcome.risk:12s} "
                  f"executed={len(actions.EXECUTED_AUDIT)}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearsal runner")
    parser.add_argument("cases", help="rehearsal_cases.json path")
    parser.add_argument("--out", default="",
                        help="working dir (default: a fresh temp dir)")
    args = parser.parse_args(argv)

    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    base = os.path.dirname(os.path.abspath(__file__))
    policy_path = os.environ.get(
        "LAB12_POLICY_STORE",
        os.path.join(base, "..", "..", "data", "policies.json"))
    workdir = args.out or tempfile.mkdtemp(prefix="lab12-eval-")
    results = evaluate(cases, policy_path, workdir)
    n_pass = sum(1 for r in results if r["pass"])
    print(f"\n{n_pass}/{len(results)} rehearsal cases passed")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
