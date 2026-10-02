"""Lab 5 chunking: word-window chunking with overlap, per paragraph.

chunk_paragraphs(docs, chunk_size_words=120, overlap_words=20) turns each
document's paragraphs into chunks. Paragraphs shorter than chunk_size_words
stay whole, so the default config yields ~1 chunk per paragraph. Chunk ids
are "{doc_id}#c{n}".
"""
from __future__ import annotations


def chunk_paragraphs(docs: list[dict], chunk_size_words: int = 120,
                     overlap_words: int = 20) -> list[dict]:
    if chunk_size_words <= 0:
        raise ValueError("chunk_size_words must be positive")
    if not 0 <= overlap_words < chunk_size_words:
        raise ValueError("overlap_words must satisfy 0 <= overlap < chunk_size")
    chunks: list[dict] = []
    for doc in docs:
        n = 0
        for para in doc["paragraphs"]:
            words = para.split()
            if len(words) <= chunk_size_words:
                spans = [(0, len(words))]
            else:
                step = chunk_size_words - overlap_words
                spans = [(s, min(s + chunk_size_words, len(words)))
                         for s in range(0, len(words), step)]
                # drop a trailing sliver fully covered by the previous chunk
                if len(spans) > 1 and spans[-1][1] - spans[-1][0] <= overlap_words:
                    spans.pop()
            for start, end in spans:
                chunks.append({
                    "chunk_id": f"{doc['doc_id']}#c{n}",
                    "doc_id": doc["doc_id"],
                    "title": doc["title"],
                    "text": " ".join(words[start:end]),
                    "department": doc["department"],
                    "effective_date": doc["effective_date"],
                    "version": doc["version"],
                })
                n += 1
    return chunks
