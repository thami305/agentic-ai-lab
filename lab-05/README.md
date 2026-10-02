# Lab 5 — Retrieval-Augmented Adviser

Deterministic RAG over a synthetic corpus of 40 company policy/SOP documents.
Keyword + TF-IDF hybrid retrieval, proximity reranking, passage-level
citations validated by lab-02's `validate_brief`, and abstention when the
corpus has no answer. Pure Python — no numpy, no network, no model calls.

## Quickstart

```bash
cd lab-05
python3 -m venv .venv && .venv/bin/pip install pydantic pytest
export PYTHONPATH=src:../lab-02/src

# 1. generate the corpus + eval questions (seeded, deterministic)
.venv/bin/python -m lab05.generate        # writes data/corpus.json, data/eval_questions.json

# 2. run the tests
.venv/bin/python -m pytest tests -q       # 20 passed

# 3. use the CLI
.venv/bin/python -m lab05.run ask "What does the HR PTO policy state about wexford, balances?"
.venv/bin/python -m lab05.run eval
.venv/bin/python -m lab05.run experiment --var chunk_size
```

## Layout

```
lab-05/
  src/lab05/
    generate.py    seeded corpus (40 docs) + 30 eval questions -> data/
    chunk.py       word-window chunking with overlap
    retrieve.py    metadata filters, keyword overlap, TF-IDF, hybrid, reranker
    agent.py       deterministic adviser: retrieve -> brief -> validate_brief -> answer/decline
    evaluate.py    30-question eval, hit / citation / abstention scoring
    experiment.py  one-variable experiment runner (chunk_size | overlap | top_k | rerank)
    run.py         CLI: ask | eval | experiment --var
  tests/           20 deterministic tests
  data/            corpus.json, eval_questions.json (generated, committed)
  docs/architecture.md
```

lab-02 is reused via `PYTHONPATH=src:../lab-02/src`: `keywords()` /
`score_passage` from `lab02.tools`, and `Packet` / `SourceDoc` / `Passage` /
`ResearchBrief` / `Claim` / `Evidence` / `Decline` plus `validate_brief`
from lab-02.

## How it works

1. **Corpus** — 8 topics × 5 departments (HR, Finance, IT, Operations, Legal),
   each doc 3–5 paragraphs of 3–5 sentences with concrete facts. Every doc
   carries a lexically unique *signature token* (e.g. `Wexford`), so
   same-topic documents stay distinguishable to a lexical retriever.
2. **Chunking** — word windows (default 120w/20w overlap); short paragraphs
   stay whole, so default ≈ 1 chunk per paragraph.
3. **Retrieval** — metadata filter → keyword overlap + pure-Python TF-IDF
   (sublinear tf, `idf=log(N/df)`) → 0.5/0.5 min-max hybrid → proximity
   rerank over top-20 (`boost = 1/(1+min window)` for chunks matching ≥2
   query terms).
4. **Answering** — top-k chunks become lab-02 claims with verbatim
   first-sentence quotes; `validate_brief` runs on a packet built from the
   corpus. If the top chunk's keyword overlap < 2, or validation fails, the
   agent returns `Decline` (fail safe).
5. **Eval** — 26 answerable questions (gold = `{doc_id, answer_phrase}`, a
   corpus-unique substring, so scoring survives chunk-size changes) + 4
   unanswerable questions with vocabulary absent from the corpus.

## What done means

- [x] Correct passage cited on ≥27/30 → **30/30** (26/26 hits, 26/26 citations valid)
- [x] Agent abstains on all 4 unanswerable questions → **4/4**
- [x] One-variable experiment reproducible → same config twice gives identical results
- [ ] Two-minute demo recording → not produced here; the demo script is the
      three CLI commands above (`ask` → `eval` → `experiment --var top_k`),
      which run end-to-end in under a minute.

## Two-minute demo script

```bash
export PYTHONPATH=src:../lab-02/src
.venv/bin/python -m lab05.run ask "What does the IT incident response policy state about siren, bridge, page?"
# -> 3 cited claims with verbatim quotes + tokens/latency
.venv/bin/python -m lab05.run ask "What is the annual budget for the pet astronaut program?"
# -> DECLINED: no corpus passage meets the retrieval confidence threshold
.venv/bin/python -m lab05.run eval
# -> correct: 30/30, hit rate 100%, abstention 4/4, PASS: True
.venv/bin/python -m lab05.run experiment --var top_k
# -> markdown table: top_k 1/3/5 vs hit_rate, citation_ok_rate, abstention, avg_tokens
```
