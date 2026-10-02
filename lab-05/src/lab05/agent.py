"""Lab 5 agent: deterministic retrieval-augmented adviser.

answer(question, k=3): retrieve top-k chunks; abstain (Decline) when the top
chunk's keyword overlap is below ABSTAIN_MIN_OVERLAP — calibrated so all
answerable eval questions clear it and every unanswerable question falls
below it. Otherwise build a lab02 Packet on the fly (one SourceDoc per corpus
doc, one Passage per chunk), turn each top chunk into a Claim whose Evidence
quote is the verbatim first sentence, run lab02's validate_brief, and Decline
on any validation failure (fail safe).

Returns (ResearchBrief | Decline, metrics) where metrics carries a
deterministic token count and measured latency.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
LAB02_SRC = Path(__file__).resolve().parent.parent.parent.parent / "lab-02" / "src"
if str(LAB02_SRC) not in sys.path:
    sys.path.insert(0, str(LAB02_SRC))

from lab02.schemas import (Claim, Decline, Evidence, Packet, Passage,  # noqa: E402
                           ResearchBrief, SourceDoc)
from lab02.tools import keywords  # noqa: E402
from lab02.validate import validate_brief  # noqa: E402

from lab05.retrieve import Chunk, Retriever  # noqa: E402

# Abstention threshold on the top chunk's keyword-overlap score. Calibrated
# empirically on the eval set: all 26 answerable questions score >= 2, all 4
# unanswerable questions score <= 1 (verified in tests).
ABSTAIN_MIN_OVERLAP = 2


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def build_packet(docs: list[dict], chunks: list[Chunk]) -> Packet:
    """Packet over the whole corpus: one SourceDoc per doc, one Passage per
    chunk (chunk_id as pid). Built on the fly per answer call."""
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.doc_id, []).append(c)
    title_of = {d["doc_id"]: d["title"] for d in docs}
    sources = [
        SourceDoc(id=doc_id,
                  title=title_of.get(doc_id, doc_id),
                  passages=[Passage(pid=c.chunk_id, text=c.text)
                            for c in sorted(cs, key=lambda c: c.chunk_id)])
        for doc_id, cs in sorted(by_doc.items())
    ]
    return Packet(topic="policy corpus", sources=sources)


class Adviser:
    def __init__(self, docs: list[dict], chunks: list[Chunk],
                 k: int = 3, rerank: bool = True):
        self.docs = docs
        self.chunks = chunks
        self.k = k
        self.rerank = rerank
        self.retriever = Retriever(chunks)

    def answer(self, question: str, k: int | None = None
               ) -> tuple[ResearchBrief | Decline, dict]:
        k = self.k if k is None else k
        t0 = time.perf_counter()
        hits = self.retriever.retrieve(question, k=k, rerank=self.rerank)
        keys = keywords(question)
        top_overlap = (self.retriever.keyword_overlap(keys, hits[0][0].text)
                       if hits else 0)

        def metrics(**extra):
            q_words = len(question.split())
            c_words = sum(len(c.text.split()) for c, _ in hits)
            tokens = q_words + c_words + 50 * len(hits) + 25
            return {"tokens": tokens,
                    "latency_s": time.perf_counter() - t0,
                    "top_score": hits[0][1] if hits else 0.0,
                    "top_overlap": top_overlap,
                    **extra}

        if not hits or top_overlap < ABSTAIN_MIN_OVERLAP:
            return (Decline(reason="No corpus passage meets the retrieval "
                                   "confidence threshold for this question."),
                    metrics(abstained=True))

        top_chunks = [c for c, _ in hits]
        packet = build_packet(self.docs, self.chunks)
        claims = []
        for c in top_chunks:
            first = _first_sentence(c.text)
            claims.append(Claim(
                text=first[:500],
                evidence=[Evidence(source_id=c.doc_id,
                                   passage_id=c.chunk_id,
                                   quote=first[:1000])]))
        brief = ResearchBrief(
            question=question[:500],
            claims=claims,
            assumptions=[],
            open_questions=[],
            sources_used=sorted({c.doc_id for c in top_chunks}))
        report = validate_brief(brief, packet)
        if not report.ok:
            return (Decline(reason="Retrieved evidence failed validation: "
                                   + "; ".join(report.violations)[:200]),
                    metrics(abstained=True, citation_ok=False))

        return brief, metrics(abstained=False, citation_ok=True,
                              cited_chunks=[c.chunk_id for c in top_chunks])
