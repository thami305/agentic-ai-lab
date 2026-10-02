"""run_golden.py — CLI: run the golden set, emit one JSON trace per case.

Writes traces/<case_id>.json. Tests use the tracer in-memory instead.

Usage (from the lab-09 directory):
    PYTHONPATH=src:../lab-02/src:../lab-03/src .venv/bin/python -m lab09.run_golden
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gate import DEFAULT_GOLDEN
from .runner import load_golden, run_case, score_case

LAB09_ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Run golden set, emit traces")
    ap.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    ap.add_argument("--out", default=str(LAB09_ROOT / "traces"))
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    cases = load_golden(args.golden)
    passed = 0
    for case in cases:
        result = run_case(case)
        scored = score_case(case, result)
        passed += scored["pass"]
        (outdir / f"{case['id']}.json").write_text(
            json.dumps(result.trace, indent=2))
        print(f"{case['id']}: terminal={result.terminal} "
              f"{'PASS' if scored['pass'] else 'FAIL'}")
    print(f"\n{passed}/{len(cases)} cases passed; "
          f"traces in {outdir}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
