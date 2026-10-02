"""Lab 5 retrieval: metadata filters, hybrid keyword + TF-IDF, reranker.

- Metadata filter: department in [...], effective_date within [date_from,
  date_to] ("YYYY-MM" strings compare lexicographically).
- Keyword overlap: lab02's keywords()/score_passage (substring match).
- TF-IDF: pure-Python df over the chunk corpus, sublinear tf 1+log(tf),
  idf = log(N/df). No numpy.
- Hybrid: 0.5 * minmax(keyword) + 0.5 * minmax(tfidf), normalized per query.
- Reranker: keyword proximity over the top-20 — chunks matching >= 2 query
  terms get boost = 1/(1 + min word window covering all matched terms),
  added to the hybrid score, then re-sorted.

All rankings break ties by chunk_id, so retrieval is fully deterministic.
"""
from __future__ import annotations

import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
LAB02_SRC = Path(__file__).resolve().parent.parent.parent.parent / "lab-02" / "src"
if str(LAB02_SRC) not in sys.path:
    sys.path.insert(0, str(LAB02_SRC))

from lab02.tools import STOPWORDS, keywords, score_passage  # noqa: E402


def _tokens(text: str) -> list[str]:
    """Same tokenization as lab02.keywords but keeps duplicates for tf."""
    toks = re.findall(r"[a-z0-9%$.]+", text.lower())
    out = []
    for t in toks:
        t = t.strip("%$.")
        if len(t) > 2 and t not in STOPWORDS:
            out.append(t)
    return out


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    department: str
    effective_date: str
    version: str

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(**{f: d[f] for f in
                      ("chunk_id", "doc_id", "title", "text",
                       "department", "effective_date", "version")})


@dataclass
class Retriever:
    chunks: list[Chunk]
    df: dict[str, int] = field(init=False)
    n: int = field(init=False)

    def __post_init__(self) -> None:
        self.n = len(self.chunks)
        df: dict[str, int] = {}
        for c in self.chunks:
            for tok in set(_tokens(c.text)):
                df[tok] = df.get(tok, 0) + 1
        self.df = df

    # ---------------------------------------------------------- filters
    def _apply_filters(self, filters: dict | None) -> list[Chunk]:
        out = self.chunks
        if not filters:
            return out
        depts = filters.get("departments")
        if depts:
            out = [c for c in out if c.department in depts]
        date_from = filters.get("date_from")
        if date_from:
            out = [c for c in out if c.effective_date >= date_from]
        date_to = filters.get("date_to")
        if date_to:
            out = [c for c in out if c.effective_date <= date_to]
        return out

    # ------------------------------------------------------------ scores
    def keyword_overlap(self, query_keys: list[str], text: str) -> int:
        return score_passage(query_keys, text)

    def tfidf(self, query_keys: list[str], text: str) -> float:
        counts = Counter(_tokens(text))
        total = 0.0
        for term in query_keys:
            df = self.df.get(term, 0)
            if df == 0:
                continue
            tf = counts.get(term, 0)
            if tf == 0:
                continue
            total += (1.0 + math.log(tf)) * math.log(self.n / df)
        return total

    @staticmethod
    def _minmax(scores: list[float]) -> list[float]:
        lo, hi = min(scores), max(scores)
        if hi == lo:
            return [0.0] * len(scores)
        return [(s - lo) / (hi - lo) for s in scores]

    @staticmethod
    def _min_window(text: str, terms: list[str]) -> int | None:
        """Smallest word window covering every matched term (>= 2 terms)."""
        words = text.split()
        events: list[tuple[int, str]] = []
        for t in terms:
            for i, w in enumerate(words):
                if t in w.lower():
                    events.append((i, t))
        if not events:
            return None
        events.sort()
        need = len(terms)
        count: dict[str, int] = {}
        have = 0
        left = 0
        best: int | None = None
        for right in range(len(events)):
            t = events[right][1]
            count[t] = count.get(t, 0) + 1
            if count[t] == 1:
                have += 1
            while have == need:
                window = events[right][0] - events[left][0] + 1
                if best is None or window < best:
                    best = window
                tl = events[left][1]
                count[tl] -= 1
                if count[tl] == 0:
                    have -= 1
                left += 1
        return best

    # ---------------------------------------------------------- retrieve
    def retrieve(self, query: str, k: int = 5,
                 filters: dict | None = None,
                 rerank: bool = True) -> list[tuple[Chunk, float]]:
        cands = self._apply_filters(filters)
        keys = keywords(query)
        kw_scores = [float(self.keyword_overlap(keys, c.text)) for c in cands]
        tf_scores = [self.tfidf(keys, c.text) for c in cands]
        nk = self._minmax(kw_scores)
        nt = self._minmax(tf_scores)
        hybrid = [0.5 * a + 0.5 * b for a, b in zip(nk, nt)]

        order = sorted(range(len(cands)),
                       key=lambda i: (-hybrid[i], cands[i].chunk_id))
        top20 = order[:20]
        final = list(hybrid)
        if rerank:
            for i in top20:
                c = cands[i]
                matched = [t for t in keys if t in c.text.lower()]
                if len(matched) >= 2:
                    window = self._min_window(c.text, matched)
                    if window:
                        final[i] = hybrid[i] + 1.0 / (1.0 + window)
            top20 = sorted(top20, key=lambda i: (-final[i], cands[i].chunk_id))
            order = top20 + [i for i in order if i not in set(top20)]

        return [(cands[i], final[i]) for i in order[:k]]
