"""Lab 5 evaluation: 30 questions, deterministic scoring.

Per-question row:
  - answerable: hit = gold answer_phrase appears in a cited chunk's text
    (implies the gold doc was retrieved — robust to chunk-size changes);
    citation_ok = lab02 validate_brief on the produced brief (recomputed here,
    independently of the agent).
  - unanswerable: correct = agent returned Decline.

correct = (answerable and hit and citation_ok) or (unanswerable and declined).
PASS: correct >= 27/30 AND abstention == 4/4.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
LAB02_SRC = Path(__file__).resolve().parent.parent.parent.parent / "lab-02" / "src"
if str(LAB02_SRC) not in sys.path:
    sys.path.insert(0, str(LAB02_SRC))

from lab02.schemas import Decline, ResearchBrief  # noqa: E402
from lab02.validate import validate_brief  # noqa: E402

from lab05.agent import Adviser, build_packet  # noqa: E402
from lab05.chunk import chunk_paragraphs  # noqa: E402
from lab05.retrieve import Chunk  # noqa: E402

PASS_MIN_CORRECT = 27


def _chunk_texts(chunks: list[Chunk]) -> dict[str, str]:
    return {c.chunk_id: c.text for c in chunks}


def run_eval(corpus: list[dict], questions: list[dict],
             chunk_size_words: int = 120, overlap_words: int = 20,
             top_k: int = 3, rerank: bool = True) -> dict:
    chunk_dicts = chunk_paragraphs(corpus, chunk_size_words, overlap_words)
    chunks = [Chunk.from_dict(d) for d in chunk_dicts]
    texts = _chunk_texts(chunks)
    adviser = Adviser(corpus, chunks, k=top_k, rerank=rerank)

    rows: list[dict] = []
    for q in questions:
        result, m = adviser.answer(q["question"])
        row: dict = {
            "qid": q["qid"],
            "question": q["question"],
            "answerable": q["answerable"],
            "abstained": isinstance(result, Decline),
            "tokens": m["tokens"],
            "latency_s": round(m["latency_s"], 4),
            "top_overlap": m["top_overlap"],
        }
        if q["answerable"]:
            phrase = q["gold"]["answer_phrase"]
            if isinstance(result, ResearchBrief):
                packet = build_packet(corpus, chunks)
                report = validate_brief(result, packet)
                cited = [ev.passage_id for cl in result.claims
                         for ev in cl.evidence]
                row["hit"] = any(phrase in texts.get(pid, "")
                                 for pid in cited)
                row["citation_ok"] = report.ok
                row["violations"] = report.violations
                row["correct"] = bool(row["hit"] and row["citation_ok"])
            else:
                row["hit"] = False
                row["citation_ok"] = None
                row["violations"] = []
                row["correct"] = False
        else:
            row["hit"] = False
            row["citation_ok"] = None
            row["violations"] = []
            row["correct"] = bool(isinstance(result, Decline))
        rows.append(row)

    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    answered = [r for r in answerable if not r["abstained"]]
    summary = {
        "n": len(rows),
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "hits": sum(1 for r in answerable if r["hit"]),
        "hit_rate": sum(1 for r in answerable if r["hit"]) / len(answerable),
        "answered": len(answered),
        "citations_ok": sum(1 for r in answered if r["citation_ok"]),
        "citation_ok_rate": (sum(1 for r in answered if r["citation_ok"])
                             / len(answered)) if answered else 1.0,
        "abstentions": sum(1 for r in unanswerable if r["abstained"]),
        "correct": sum(1 for r in rows if r["correct"]),
        "avg_tokens": sum(r["tokens"] for r in rows) / len(rows),
        "avg_latency_s": sum(r["latency_s"] for r in rows) / len(rows),
    }
    summary["passed"] = (summary["correct"] >= PASS_MIN_CORRECT
                         and summary["abstentions"] == len(unanswerable))
    return {"rows": rows, "summary": summary,
            "config": {"chunk_size_words": chunk_size_words,
                       "overlap_words": overlap_words,
                       "top_k": top_k, "rerank": rerank}}


def load_data(data_dir: Path) -> tuple[list[dict], list[dict]]:
    corpus = json.loads((data_dir / "corpus.json").read_text())
    questions = json.loads((data_dir / "eval_questions.json").read_text())
    return corpus, questions


def print_summary(results: dict) -> None:
    s = results["summary"]
    c = results["config"]
    print(f"config: chunk_size={c['chunk_size_words']} overlap={c['overlap_words']} "
          f"top_k={c['top_k']} rerank={c['rerank']}")
    print(f"correct:            {s['correct']}/{s['n']}")
    print(f"hit rate:           {s['hits']}/{s['n_answerable']} "
          f"({s['hit_rate']:.1%})")
    print(f"citation ok rate:   {s['citations_ok']}/{s['answered']} "
          f"({s['citation_ok_rate']:.1%})")
    print(f"abstention:         {s['abstentions']}/{s['n_unanswerable']}")
    print(f"avg tokens:         {s['avg_tokens']:.0f}")
    print(f"avg latency:        {s['avg_latency_s']:.3f}s")
    print(f"PASS:               {s['passed']}")
    bad = [r["qid"] for r in results["rows"] if not r["correct"]]
    if bad:
        print(f"incorrect qids:     {', '.join(bad)}")
