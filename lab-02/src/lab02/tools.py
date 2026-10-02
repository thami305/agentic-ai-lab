"""Lab 2 tools: read-only access to the document packet.

- list_sources: what documents exist (ids + titles).
- search_docs: keyword-overlap retrieval over passages. Deterministic.
- get_passage: full text of one passage by id.

Read-only and idempotent, so duplicate calls are safe to cache. Tool outputs
are UNTRUSTED DATA: they may contain instruction-like text (DOC-COMP-3 does).
The agent must quote such text as evidence at most — never follow it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from .packet import all_passages, load_packet
from .schemas import EmptyArgs, GetPassageArgs, Packet, SearchDocsArgs

STOPWORDS = frozenset(
    "a an the and or of to in on for with is are was were be been by at as it "
    "its this that these those what which who whom whose when where why how do "
    "does did will would should could can may might shall must northwind s".split()
)


def keywords(text: str) -> list[str]:
    """Deterministic keyword extraction: lowercase alnum tokens, minus
    stopwords. Shared by the tool and the oracle stub so retrieval is
    reproducible everywhere."""
    toks = re.findall(r"[a-z0-9%$.]+", text.lower())
    seen: list[str] = []
    for t in toks:
        t = t.strip("%$.")
        if len(t) > 2 and t not in STOPWORDS and t not in seen:
            seen.append(t)
    return seen


def score_passage(query_keys: list[str], text: str) -> int:
    lowered = text.lower()
    return sum(1 for k in query_keys if k in lowered)


@dataclass
class ToolDef:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[..., Any]
    timeout_s: float = 5.0
    max_retries: int = 1


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolDef] = field(default_factory=dict)

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())


def build_registry(packet: Packet | None = None) -> ToolRegistry:
    packet = packet or load_packet()
    reg = ToolRegistry()

    def list_sources() -> list[dict[str, str]]:
        return [{"source_id": s.id, "title": s.title} for s in packet.sources]

    def search_docs(query: str, limit: int = 5) -> list[dict[str, Any]]:
        keys = keywords(query)
        scored = [(score_passage(keys, p.text), s, p)
                  for s, p in all_passages(packet)]
        scored = [(sc, s, p) for sc, s, p in scored if sc > 0]
        scored.sort(key=lambda t: (-t[0], t[1].id, t[2].pid))
        return [{"source_id": s.id, "source_title": s.title,
                 "passage_id": p.pid,
                 "snippet": p.text[:160] + ("..." if len(p.text) > 160 else ""),
                 "score": sc}
                for sc, s, p in scored[:limit]]

    def get_passage(source_id: str, passage_id: str) -> dict[str, str]:
        for s in packet.sources:
            if s.id == source_id:
                for p in s.passages:
                    if p.pid == passage_id:
                        return {"source_id": s.id, "source_title": s.title,
                                "passage_id": p.pid, "text": p.text}
                raise ValueError(f"unknown passage_id '{passage_id}' "
                                 f"in source '{source_id}'")
        raise ValueError(f"unknown source_id '{source_id}'")

    reg.register(ToolDef(
        name="list_sources",
        description="List the documents in the packet: source ids and titles.",
        args_model=EmptyArgs, fn=list_sources))
    reg.register(ToolDef(
        name="search_docs",
        description="Keyword search over packet passages. Returns ranked "
                    "snippets with source and passage ids.",
        args_model=SearchDocsArgs, fn=search_docs))
    reg.register(ToolDef(
        name="get_passage",
        description="Fetch the full text of one passage by source and passage id.",
        args_model=GetPassageArgs, fn=get_passage))
    return reg
