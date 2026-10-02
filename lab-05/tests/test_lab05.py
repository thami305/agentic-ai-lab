"""Lab 5 tests — deterministic, no network, no numpy."""
from __future__ import annotations

import json

from lab02.schemas import Decline, ResearchBrief
from lab02.tools import keywords, score_passage

from lab05.chunk import chunk_paragraphs
from lab05.retrieve import Chunk, Retriever


def _doc(chunk_id="d1#c0", doc_id="d1", text="hello world",
         department="HR", effective_date="2025-06", version="v1.0"):
    return {"chunk_id": chunk_id, "doc_id": doc_id, "title": "t",
            "text": text, "department": department,
            "effective_date": effective_date, "version": version}


# ---------------------------------------------------------------- chunker

def test_chunk_word_counts_respect_size_overlap():
    docs = [{"doc_id": "d1", "title": "t", "department": "HR",
             "effective_date": "2025-01", "version": "v1.0",
             "paragraphs": [" ".join(f"w{i}" for i in range(100))]}]
    chunks = chunk_paragraphs(docs, chunk_size_words=40, overlap_words=10)
    assert len(chunks) == 3  # [0:40] [30:70] [60:100] (10-word sliver dropped)
    assert len(chunks[0]["text"].split()) == 40
    assert len(chunks[1]["text"].split()) == 40
    # overlap: chunk1 starts 30 words in, sharing 10 with chunk0
    assert chunks[1]["text"].split()[:10] == chunks[0]["text"].split()[-10:]
    assert chunks[0]["chunk_id"] == "d1#c0"


def test_short_paragraph_stays_whole():
    docs = [{"doc_id": "d1", "title": "t", "department": "HR",
             "effective_date": "2025-01", "version": "v1.0",
             "paragraphs": ["short paragraph here"]}]
    chunks = chunk_paragraphs(docs, chunk_size_words=120, overlap_words=20)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "short paragraph here"


def test_chunk_ids_unique_and_shaped(chunks):
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids)
    assert all(c.chunk_id == f"{c.doc_id}#c{i}" or "#" in c.chunk_id
               for i, c in enumerate(chunks))
    assert all(c.chunk_id.startswith(c.doc_id + "#c") for c in chunks)


# --------------------------------------------------------------- filters

def test_metadata_filter_department(chunks):
    r = Retriever(chunks)
    hits = r.retrieve("policy", k=200, filters={"departments": ["IT"]})
    assert hits
    assert all(c.department == "IT" for c, _ in hits)


def test_metadata_filter_date_range(chunks):
    r = Retriever(chunks)
    hits = r.retrieve("policy", k=200,
                       filters={"date_from": "2025-01", "date_to": "2025-12"})
    assert hits
    assert all("2025-01" <= c.effective_date <= "2025-12" for c, _ in hits)


# ---------------------------------------------------------------- scoring

def test_keyword_overlap_unit():
    assert score_passage(["pto", "accrue"], "Employees accrue PTO days") == 2
    assert score_passage(["yacht"], "Employees accrue PTO days") == 0


def test_tfidf_rare_term_outranks():
    docs = [_doc("d1#c0", "d1", "alpha zebra"),
            _doc("d2#c0", "d2", "alpha"),
            _doc("d3#c0", "d3", "alpha")]
    r = Retriever([Chunk.from_dict(d) for d in docs])
    # 'zebra' in 1 chunk outranks 'alpha' in all 3
    assert r.tfidf(["zebra"], "alpha zebra") > r.tfidf(["alpha"], "alpha zebra")
    hits = r.retrieve("zebra alpha", k=3, rerank=False)
    assert hits[0][0].chunk_id == "d1#c0"


def test_reranker_proximity():
    docs = [_doc("a#c0", "a", "quick fox"),
            _doc("b#c0", "b", "quick " + "word " * 30 + "fox")]
    r = Retriever([Chunk.from_dict(d) for d in docs])
    assert Retriever._min_window("quick fox", ["quick", "fox"]) == 2
    assert Retriever._min_window(docs[1]["text"], ["quick", "fox"]) == 32
    plain = r.retrieve("quick fox", k=2, rerank=False)
    ranked = r.retrieve("quick fox", k=2, rerank=True)
    # identical term sets -> hybrid tie, broken by chunk_id ...
    assert plain[0][1] == plain[1][1]
    # ... but with the reranker the close-together chunk genuinely outscores
    assert ranked[0][0].chunk_id == "a#c0"
    assert ranked[0][1] > ranked[1][1]


def test_retrieve_top_k_ranked(adviser):
    hits = adviser.retriever.retrieve("pto policy", k=3)
    assert len(hits) == 3
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


# -------------------------------------------------------------- generator

def test_generator_determinism(tmp_path):
    from lab05.generate import generate_corpus
    b1 = json.dumps(generate_corpus(42), indent=2, sort_keys=True).encode()
    b2 = json.dumps(generate_corpus(42), indent=2, sort_keys=True).encode()
    assert b1 == b2
    (tmp_path / "a.json").write_bytes(b1)
    (tmp_path / "b.json").write_bytes(b2)
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_corpus_has_40_docs_with_metadata(corpus):
    assert len(corpus) == 40
    for d in corpus:
        assert set(d) >= {"doc_id", "department", "version",
                          "effective_date", "title", "paragraphs"}
        assert d["department"] in {"HR", "Finance", "IT", "Operations", "Legal"}
        assert d["version"].startswith("v")
        assert 3 <= len(d["paragraphs"]) <= 6
        assert all(len(p.split()) >= 2 for p in d["paragraphs"])


# ------------------------------------------------------------------- eval

def test_eval_correct_ge_27(eval_results):
    assert eval_results["summary"]["correct"] >= 27


def test_citation_validity_all_answered(eval_results):
    rows = eval_results["rows"]
    answered = [r for r in rows if r["answerable"] and not r["abstained"]]
    assert len(answered) == 26
    assert all(r["citation_ok"] for r in answered)


def test_abstention_4_of_4(eval_results):
    s = eval_results["summary"]
    assert s["n_unanswerable"] == 4
    assert s["abstentions"] == 4


def test_unanswerable_max_overlap_le_1(corpus, questions, chunks):
    for q in questions:
        if q["answerable"]:
            continue
        keys = keywords(q["question"])
        worst = max(score_passage(keys, c.text) for c in chunks)
        assert worst <= 1, q["qid"]


def test_tokens_latency_recorded(eval_results):
    for r in eval_results["rows"]:
        assert r["tokens"] > 0
        assert r["latency_s"] >= 0


def test_answer_faithfulness(adviser, questions, chunks):
    texts = {c.chunk_id: c.text for c in chunks}
    n_checked = 0
    for q in questions:
        if not q["answerable"]:
            continue
        result, _ = adviser.answer(q["question"])
        assert isinstance(result, ResearchBrief)
        for claim in result.claims:
            for ev in claim.evidence:
                assert ev.quote in texts[ev.passage_id], (
                    f"non-verbatim quote in {q['qid']}")
                n_checked += 1
    assert n_checked >= 26


def test_decline_shape(adviser, questions):
    uq = next(q for q in questions if not q["answerable"])
    result, metrics = adviser.answer(uq["question"])
    assert isinstance(result, Decline)
    assert 5 <= len(result.reason) <= 300
    assert metrics["abstained"] is True


# ------------------------------------------------------------ experiment

def test_experiment_reproducibility(corpus, questions):
    from lab05.experiment import run_experiment
    r1 = run_experiment("top_k", [1, 3], corpus, questions)
    r2 = run_experiment("top_k", [1, 3], corpus, questions)
    strip = lambda r: {k: {kk: vv for kk, vv in v.items()
                           if kk != "avg_latency_s"}
                       for k, v in r.items()}
    assert strip(r1) == strip(r2)


def test_experiment_table_multiple_rows(corpus, questions, capsys):
    from lab05.experiment import run_experiment
    results = run_experiment("rerank", [True, False], corpus, questions)
    assert len(results) == 2
    out = capsys.readouterr().out
    assert "| True |" in out and "| False |" in out
