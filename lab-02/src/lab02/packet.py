"""The curated document packet: the only ground truth the agent may cite.

Five sources, nineteen passages, one topic. One passage (DOC-COMP-3) carries
an instruction-injection payload — tool output is untrusted data, and the
tests assert the agent quotes it as evidence at most, never adopts it.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .schemas import Packet, Passage, SourceDoc

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@lru_cache(maxsize=1)
def load_packet(path: str | Path | None = None) -> Packet:
    raw = json.loads(Path(path or DATA_DIR / "packet.json").read_text())
    return Packet(**raw)


def passage_index(packet: Packet) -> dict[str, dict[str, Passage]]:
    """source_id -> passage_id -> Passage, for O(1) citation checks."""
    return {s.id: {p.pid: p for p in s.passages} for s in packet.sources}


def all_passages(packet: Packet) -> list[tuple[SourceDoc, Passage]]:
    return [(s, p) for s in packet.sources for p in s.passages]
