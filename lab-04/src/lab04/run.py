"""Demo CLI for Lab 4.

    python -m lab04.run demo

Runs the full story end to end: start a run with CrashPolicy, watch it
crash after retrieval, resume from a fresh store and graph (the fresh
process simulation), land on the approval interrupt, then approve and
publish.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[2]
DATA = LAB_ROOT / "data" / "packet.json"
QUESTION = "How utilized is Northwind's current warehouse?"


def demo() -> None:
    from lab02.schemas import Packet
    from lab03.policies import OraclePolicy
    from lab03.state import BriefState

    from lab04.checkpoint import CheckpointStore
    from lab04.interrupt import build_interrupt_graph, resume
    from lab04.policies import CrashPolicy
    from lab04.runner import resume_run, run_persistent

    runs_dir = LAB_ROOT / "data" / "demo-runs"
    run_id = "demo-run"
    packet = Packet(**json.loads(DATA.read_text(encoding="utf-8")))

    print("1. starting run with CrashPolicy (crash lands after retrieve)")
    store = CheckpointStore(runs_dir)
    graph = build_interrupt_graph(CrashPolicy())
    try:
        run_persistent(graph, BriefState(question=QUESTION, packet=packet),
                       store, run_id)
        print("   ERROR: expected a crash, the run completed")
        sys.exit(1)
    except RuntimeError as e:
        print(f"   crashed as planned: {e}")
    cp = store.load(run_id)
    print(f"   checkpoint on disk: status={cp.status}, "
          f"next_node={cp.next_node}, passages={len(cp.state.passages)}")

    print("2. resuming from a fresh process (new store, new graph)")
    fresh_store = CheckpointStore(runs_dir)
    final = resume_run(run_id, fresh_store, build_interrupt_graph,
                       OraclePolicy())
    print(f"   resumed: terminal={final.terminal}")
    print(f"   reason: {final.terminal_reason}")
    print(f"   evidence preserved: {len(final.passages)} passages, "
          f"{len(final.brief.claims)} claims")

    print("3. human approves")
    decision = resume(run_id, "approve", fresh_store)
    done = fresh_store.load(run_id)
    print(f"   decision={decision}, status={done.status}, "
          f"terminal={done.state.terminal}")
    print(f"   side effects: "
          f"{fresh_store.side_effect_records(run_id)}")
    print("demo complete: crash, resume, approval, publish.")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "demo":
        demo()
        return 0
    print("usage: python -m lab04.run demo")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
