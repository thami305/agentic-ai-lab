"""Lab 3 CLI.

Deterministic (no API key needed):

    PYTHONPATH=src:../lab-02/src python -m lab03.run "How utilized is Northwind's current warehouse?"
    PYTHONPATH=src:../lab-02/src python -m lab03.run "When does finance expect the second site to break even?"
    PYTHONPATH=src:../lab-02/src python -m lab03.run ""

Prints the path taken through the graph, the terminal state, and the brief
(or the reason it stopped).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "lab-02" / "src"))

from lab03.nodes import build_graph  # noqa: E402
from lab03.state import BriefState  # noqa: E402
from lab02.packet import load_packet  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lab03.run",
                                 description="Lab 3: orchestration and state")
    ap.add_argument("question", nargs="?", default="")
    args = ap.parse_args(argv)

    packet = load_packet(HERE.parent.parent / "data" / "packet.json")
    state = BriefState(question=args.question, packet=packet)
    graph = build_graph()
    graph.run(state)

    print("path:     " + " -> ".join(state.path))
    print(f"terminal: {state.terminal}")
    print(f"reason:   {state.terminal_reason}")
    print(f"retrieval_retries: {state.retrieval_retries}  "
          f"tool_calls: {state.tool_calls_made}  tokens: {state.total_tokens}")
    if state.brief is not None:
        print(state.brief.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
