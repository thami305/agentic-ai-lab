"""Lab 5 CLI.

    python -m lab05.run ask "What does the HR PTO policy state about ...?"
    python -m lab05.run eval
    python -m lab05.run experiment --var chunk_size

Run with PYTHONPATH=src:../lab-02/src from the lab-05 directory.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
LAB02_SRC = Path(__file__).resolve().parent.parent.parent.parent / "lab-02" / "src"
if str(LAB02_SRC) not in sys.path:
    sys.path.insert(0, str(LAB02_SRC))

from lab02.schemas import ResearchBrief  # noqa: E402

from lab05.agent import Adviser  # noqa: E402
from lab05.chunk import chunk_paragraphs  # noqa: E402
from lab05.evaluate import load_data, print_summary, run_eval  # noqa: E402
from lab05.experiment import VARIABLES, run_experiment  # noqa: E402
from lab05.retrieve import Chunk  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def cmd_ask(question: str) -> None:
    corpus, _ = load_data(DATA_DIR)
    chunks = [Chunk.from_dict(d) for d in chunk_paragraphs(corpus)]
    adviser = Adviser(corpus, chunks)
    result, metrics = adviser.answer(question)
    print(f"Q: {question}\n")
    if isinstance(result, ResearchBrief):
        for i, claim in enumerate(result.claims, 1):
            ev = claim.evidence[0]
            print(f"[{i}] {claim.text}")
            print(f"    ({ev.source_id} / {ev.passage_id}) "
                  f"\"{ev.quote}\"")
        print(f"\nsources: {', '.join(result.sources_used)}")
    else:
        print(f"DECLINED: {result.reason}")
    print(f"\ntokens={metrics['tokens']} "
          f"latency={metrics['latency_s']:.3f}s "
          f"top_overlap={metrics['top_overlap']}")


def cmd_eval() -> None:
    corpus, questions = load_data(DATA_DIR)
    print_summary(run_eval(corpus, questions))


def cmd_experiment(var: str) -> None:
    corpus, questions = load_data(DATA_DIR)
    run_experiment(var, None, corpus, questions)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="lab05.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_ask = sub.add_parser("ask", help="answer one question")
    p_ask.add_argument("question")
    sub.add_parser("eval", help="run the 30-question eval")
    p_exp = sub.add_parser("experiment", help="one-variable experiment")
    p_exp.add_argument("--var", choices=sorted(VARIABLES), required=True)
    args = ap.parse_args(argv)
    if args.cmd == "ask":
        cmd_ask(args.question)
    elif args.cmd == "eval":
        cmd_eval()
    elif args.cmd == "experiment":
        cmd_experiment(args.var)


if __name__ == "__main__":
    main()
