"""Lab 5 experiment runner: change ONE variable, re-run the eval.

Variables and value grids:
  chunk_size -> [60, 120, 200]   (chunk_size_words; overlap stays 20)
  overlap    -> [0, 20, 40]      (overlap_words; chunk_size stays 120)
  top_k      -> [1, 3, 5]
  rerank     -> [True, False]

Same config twice -> identical results (pure-Python, seeded, deterministic
tie-breaks; only wall-clock latency varies and is reported separately).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab05.evaluate import run_eval  # noqa: E402

DEFAULTS = {"chunk_size_words": 120, "overlap_words": 20,
            "top_k": 3, "rerank": True}

VARIABLES: dict[str, list] = {
    "chunk_size": [60, 120, 200],
    "overlap": [0, 20, 40],
    "top_k": [1, 3, 5],
    "rerank": [True, False],
}

_CONFIG_KEY = {"chunk_size": "chunk_size_words", "overlap": "overlap_words",
               "top_k": "top_k", "rerank": "rerank"}


def run_experiment(variable: str, values: list | None,
                   corpus: list[dict], questions: list[dict]) -> dict:
    if variable not in VARIABLES:
        raise ValueError(f"unknown variable {variable!r}; "
                         f"choose from {sorted(VARIABLES)}")
    values = VARIABLES[variable] if values is None else values
    results: dict[str, dict] = {}
    for v in values:
        cfg = dict(DEFAULTS)
        cfg[_CONFIG_KEY[variable]] = v
        res = run_eval(corpus, questions, **cfg)
        s = res["summary"]
        results[str(v)] = {
            "hit_rate": round(s["hit_rate"], 4),
            "citation_ok_rate": round(s["citation_ok_rate"], 4),
            "abstention": f"{s['abstentions']}/{s['n_unanswerable']}",
            "abstention_n": s["abstentions"],
            "avg_tokens": round(s["avg_tokens"], 1),
            "avg_latency_s": round(s["avg_latency_s"], 4),
            "correct": f"{s['correct']}/{s['n']}",
            "correct_n": s["correct"],
        }
    print(format_table(variable, results))
    return results


def format_table(variable: str, results: dict[str, dict]) -> str:
    lines = [
        f"| {variable} | hit_rate | citation_ok_rate | abstention "
        f"| avg_tokens | correct |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for setting, m in results.items():
        lines.append(
            f"| {setting} | {m['hit_rate']:.2f} | {m['citation_ok_rate']:.2f} "
            f"| {m['abstention']} | {m['avg_tokens']:.0f} | {m['correct']} |")
    return "\n".join(lines)
