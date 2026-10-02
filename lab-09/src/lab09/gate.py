"""Lab 9 merge gate: thresholds stay green, or nothing merges.

Reads thresholds from eval/thresholds.json (NEVER hardcoded — the gate takes
a thresholds path). Runs the full golden set plus the calibration subset and
returns red/green per threshold:

  min_pass_rate:        fraction of golden cases passing deterministic checks
  max_unsupported_claims: worst per-case count of citation-invalid claims
  min_agreement:        stub-grader vs deterministic agreement on calibration

"A prompt, model, or tool change cannot merge unless thresholds stay green."
The centerpiece regression test disables lab02's citation post-validator and
asserts the gate goes red.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .grader import StubGrader, load_calibration
from .runner import load_golden, run_case, score_case

LAB09_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_GOLDEN = LAB09_ROOT / "data" / "golden.jsonl"
DEFAULT_CALIBRATION = LAB09_ROOT / "data" / "calibration.jsonl"
DEFAULT_THRESHOLDS = LAB09_ROOT / "eval" / "thresholds.json"


def load_thresholds(path: str | Path | None = None) -> dict[str, Any]:
    with open(Path(path) if path else DEFAULT_THRESHOLDS) as f:
        return json.load(f)


def run_gate(golden_path: str | Path | None = None,
             calibration_path: str | Path | None = None,
             thresholds_path: str | Path | None = None) -> dict[str, Any]:
    thresholds = load_thresholds(thresholds_path)
    cases = load_golden(golden_path or DEFAULT_GOLDEN)

    passed = 0
    worst_unsupported = 0
    failures: list[str] = []
    for case in cases:
        result = run_case(case)
        scored = score_case(case, result)
        if scored["pass"]:
            passed += 1
        else:
            bad = [n for n, c in scored["checks"].items() if not c["pass"]]
            failures.append(f"{case['id']}: failed checks {bad}")
        worst_unsupported = max(worst_unsupported,
                                scored["unsupported_claims"])

    pass_rate = passed / len(cases) if cases else 0.0

    grader = StubGrader()
    labeled = load_calibration(calibration_path or DEFAULT_CALIBRATION)
    agreement = grader.agreement(
        labeled,
        lambda case, res: "pass" if score_case(case, res)["pass"] else "fail")

    checks = {
        "pass_rate": {
            "value": round(pass_rate, 4),
            "threshold": thresholds["min_pass_rate"],
            "op": ">=",
            "pass": pass_rate >= thresholds["min_pass_rate"],
        },
        "max_unsupported_claims": {
            "value": worst_unsupported,
            "threshold": thresholds["max_unsupported_claims"],
            "op": "<=",
            "pass": worst_unsupported <= thresholds["max_unsupported_claims"],
        },
        "grader_agreement": {
            "value": round(agreement["rate"], 4),
            "threshold": thresholds["min_agreement"],
            "op": ">=",
            "pass": agreement["rate"] >= thresholds["min_agreement"],
        },
    }
    green = all(c["pass"] for c in checks.values())
    return {
        "green": green,
        "verdict": "GREEN" if green else "RED",
        "cases_total": len(cases),
        "cases_passed": passed,
        "checks": checks,
        "failing_cases": failures,
        "calibration": {k: v for k, v in agreement.items()
                        if k != "mismatches"},
        "calibration_mismatches": agreement["mismatches"],
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Lab 9 merge gate")
    ap.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    ap.add_argument("--calibration", default=str(DEFAULT_CALIBRATION))
    ap.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    report = run_gate(args.golden, args.calibration, args.thresholds)
    print(f"gate: {report['verdict']} "
          f"({report['cases_passed']}/{report['cases_total']} cases)")
    for name, c in report["checks"].items():
        status = "ok" if c["pass"] else "FAIL"
        print(f"  [{status}] {name}: {c['value']} {c['op']} {c['threshold']}")
    for f in report["failing_cases"]:
        print(f"  failing case: {f}")
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(report, fh, indent=2)
    return 0 if report["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
