"""Lab 10 CLI — run one or all attack cases, print DENIED/ALLOWED + audit tail.

Examples:
    python -m lab10.run --all
    python -m lab10.run --case spoofed_approval
    python -m lab10.run --all --audit data/audit/   # persist audit logs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab10.audit import AuditLog  # noqa: E402
from lab10.cases import CASE_IDS, load_case_meta, run_case  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lab 10: adversarial action harness")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true",
                       help="run all 10 attack cases")
    group.add_argument("--case", choices=CASE_IDS, help="run one case")
    group.add_argument("--list", action="store_true", help="list the cases")
    parser.add_argument("--audit", default=None,
                        help="directory to persist per-case audit logs "
                             "(JSON lines)")
    parser.add_argument("--tail", type=int, default=4,
                        help="audit tail lines to print per case")
    args = parser.parse_args()

    if args.list:
        for meta in load_case_meta():
            print(f"{meta['id']:28s} {meta['title']}")
        return 0

    ids = CASE_IDS if args.all else [args.case]
    audit_dir = Path(args.audit) if args.audit else None

    failures = 0
    for case_id in ids:
        audit = (AuditLog(audit_dir / f"{case_id}.jsonl")
                 if audit_dir else AuditLog())
        result, case = run_case(case_id, audit=audit)
        denied, detail = case.check(result, case)
        verdict = "DENIED " if denied else "ALLOWED  *** ATTACK SUCCEEDED ***"
        if not denied:
            failures += 1
        print(f"[{verdict}] {case_id}: {detail}")
        for entry in audit.tail(args.tail):
            print(f"    audit #{entry['seq']:02d} {entry['event']:26s} "
                  f"{entry['reason'] or ''}"[:160])
        print()

    print(f"{len(ids) - failures}/{len(ids)} attacks denied.")
    ok, msg = AuditLog().verify_chain()  # sanity: empty chain verifies
    assert ok, msg
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
