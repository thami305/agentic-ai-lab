"""Lab 5 — retrieval-augmented adviser over a synthetic policy corpus.

Deterministic RAG: seeded corpus generation, word-window chunking, hybrid
keyword + TF-IDF retrieval, proximity reranking, passage-level citations
validated by lab-02's validate_brief, and abstention when the corpus has no
answer. Pure Python — no numpy.
"""

__version__ = "0.1.0"
