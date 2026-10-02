"""Policy store + keyword retriever.

The policy store is a small synthetic set of policies loaded from
data/policies.json. Retrieval is deterministic keyword overlap, reusing
Lab 2's `keywords()` (PYTHONPATH includes ../lab-02/src) — shared, not
copied. Every citation carries a verbatim quote; citations are checked
against the store text, never invented.

The store can be *down*: a missing/corrupt file, or LAB12_POLICY_OUTAGE=1,
raises PolicyStoreError. The copilot catches it and degrades instead of
crashing — see copilot.py and the outage rehearsal case.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from lab02.tools import keywords, score_passage


class PolicyStoreError(RuntimeError):
    """The policy store is unavailable (missing file, corrupt JSON, or the
    outage switch). Callers must degrade, never crash."""


class PolicySection(BaseModel):
    section: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=2000)


class Policy(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    sections: list[PolicySection] = Field(min_length=1)


class Citation(BaseModel):
    """One citation: policy id, section name, and a verbatim quote."""

    policy_id: str
    section: str
    quote: str


@dataclass
class PolicyStore:
    path: str
    _policies: list[Policy] = field(default_factory=list, repr=False)

    @classmethod
    def load(cls, path: str, force_down: bool = False) -> "PolicyStore":
        if force_down or os.environ.get("LAB12_POLICY_OUTAGE") == "1":
            raise PolicyStoreError(
                f"policy store unavailable (outage switch set; path={path})")
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError as e:
            raise PolicyStoreError(f"policy store file not found: {path}") from e
        except json.JSONDecodeError as e:
            raise PolicyStoreError(f"policy store file is corrupt: {path}") from e
        store = cls(path=path)
        try:
            store._policies = [Policy.model_validate(p) for p in raw["policies"]]
        except Exception as e:
            raise PolicyStoreError(f"policy store failed validation: {e}") from e
        return store

    @property
    def policies(self) -> list[Policy]:
        return list(self._policies)

    def full_text(self, citation: Citation) -> str:
        """Look up the section a citation claims to quote. Raises KeyError
        for anything not in the store — the anti-fabrication check."""
        for p in self._policies:
            if p.id == citation.policy_id:
                for s in p.sections:
                    if s.section == citation.section:
                        return s.text
        raise KeyError(f"no such section: {citation.policy_id}/{citation.section}")


def _matching_sentence(text: str, query_keys: list[str]) -> str:
    """The first sentence sharing a keyword with the query; fallback to the
    first sentence. Quotes are always verbatim substrings of the text."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    for s in sentences:
        if any(k in s.lower() for k in query_keys):
            return s
    return sentences[0]


def retrieve(store: PolicyStore, query: str, limit: int = 3) -> list[Citation]:
    """Deterministic keyword retrieval over policy sections. Returns citations
    with verbatim quotes. No matches -> empty list (not an error)."""
    keys = keywords(query)
    scored: list[tuple[int, Policy, PolicySection]] = []
    for policy in store.policies:
        for section in policy.sections:
            score = score_passage(keys, section.text)
            if score > 0:
                scored.append((score, policy, section))
    scored.sort(key=lambda t: (-t[0], t[1].id, t[2].section))
    return [
        Citation(policy_id=p.id, section=s.section,
                 quote=_matching_sentence(s.text, keys))
        for _, p, s in scored[:limit]
    ]
