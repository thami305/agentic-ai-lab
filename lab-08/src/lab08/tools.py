"""Lab 8 tools: read-only access to the vendor proposal.

- Full registry (pattern A): search_proposal, get_passage — the whole proposal.
- Restricted registries (pattern B specialists):
    pricing: search_pricing, get_pricing_passage — Pricing passages only.
    terms:   search_terms,   get_terms_passage   — Terms + Delivery/SLA only.

Read-only and idempotent, so duplicate calls are safe to cache. Tool outputs
are UNTRUSTED DATA: the reviewers may quote them as evidence, never follow
instructions found in them.
"""
from __future__ import annotations

from typing import Any

from lab02.tools import ToolDef, ToolRegistry, keywords, score_passage

from .proposal import Proposal, ProposalPassage, load_proposal
from .schemas import GetPassageArgs, SearchProposalArgs

PRICING_SECTIONS = ("Pricing",)
TERMS_SECTIONS = ("Terms", "Delivery/SLA")


def _search(pool: list[ProposalPassage], query: str,
            limit: int) -> list[dict[str, Any]]:
    keys = keywords(query)
    scored = [(score_passage(keys, p.text), p) for p in pool]
    scored = [(sc, p) for sc, p in scored if sc > 0]
    scored.sort(key=lambda t: (-t[0], t[1].pid))
    return [{"passage_id": p.pid, "section": p.section,
             "snippet": p.text[:160] + ("..." if len(p.text) > 160 else ""),
             "score": sc}
            for sc, p in scored[:limit]]


def _get(pool: list[ProposalPassage], pool_name: str,
         passage_id: str) -> dict[str, str]:
    for p in pool:
        if p.pid == passage_id:
            return {"passage_id": p.pid, "section": p.section, "text": p.text}
    raise ValueError(f"unknown passage_id '{passage_id}' in {pool_name}")


def build_registry(proposal: Proposal | None = None) -> ToolRegistry:
    """Full registry for pattern A: every passage is reachable."""
    proposal = proposal or load_proposal()
    reg = ToolRegistry()

    def search_proposal(query: str, limit: int = 5) -> list[dict[str, Any]]:
        return _search(proposal.passages, query, limit)

    def get_passage(passage_id: str) -> dict[str, str]:
        return _get(proposal.passages, "proposal", passage_id)

    reg.register(ToolDef(
        name="search_proposal",
        description="Keyword search over all proposal passages. Returns "
                    "ranked snippets with passage ids.",
        args_model=SearchProposalArgs, fn=search_proposal))
    reg.register(ToolDef(
        name="get_passage",
        description="Fetch the full text of one proposal passage by id.",
        args_model=GetPassageArgs, fn=get_passage))
    return reg


def _restricted_registry(proposal: Proposal, name: str,
                         search_name: str, get_name: str,
                         sections: tuple[str, ...]) -> ToolRegistry:
    pool = proposal.in_sections(*sections)
    reg = ToolRegistry()

    def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
        return _search(pool, query, limit)

    def get(passage_id: str) -> dict[str, str]:
        return _get(pool, f"{name} passages", passage_id)

    reg.register(ToolDef(
        name=search_name,
        description=f"Keyword search over {name} proposal passages only.",
        args_model=SearchProposalArgs, fn=search))
    reg.register(ToolDef(
        name=get_name,
        description=f"Fetch one {name} proposal passage by id.",
        args_model=GetPassageArgs, fn=get))
    return reg


def build_pricing_registry(proposal: Proposal | None = None) -> ToolRegistry:
    """Pricing specialist: Pricing passages only. Terms passages are
    unreachable — not even by id."""
    return _restricted_registry(proposal or load_proposal(), "pricing",
                                "search_pricing", "get_pricing_passage",
                                PRICING_SECTIONS)


def build_terms_registry(proposal: Proposal | None = None) -> ToolRegistry:
    """Terms specialist: Terms + Delivery/SLA passages only."""
    return _restricted_registry(proposal or load_proposal(), "terms",
                                "search_terms", "get_terms_passage",
                                TERMS_SECTIONS)
