"""Deterministic post-validation for Lab 2 briefs.

The model proposes; this code decides whether the brief may ship. Checks:

1. Every claim carries at least one evidence entry.
2. Every evidence entry names a real source_id and passage_id from the packet.
3. Every quote is a verbatim substring of the cited passage (whitespace
   normalized) — citations must survive formatting; fabricated quotes fail.
4. No claim text is empty or trivially short (schema already enforces length).

Unsupported material must live in open_questions, never in claims: claims are
by construction supported-or-rejected here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .packet import passage_index
from .schemas import Packet, ResearchBrief


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ValidationReport:
    ok: bool
    violations: list[str] = field(default_factory=list)


def validate_brief(brief: ResearchBrief, packet: Packet) -> ValidationReport:
    violations: list[str] = []
    index = passage_index(packet)

    if not brief.claims:
        violations.append("brief has no claims")

    for i, claim in enumerate(brief.claims):
        tag = f"claim[{i}]"
        if not claim.evidence:
            violations.append(f"{tag}: no evidence entries")
            continue
        for j, ev in enumerate(claim.evidence):
            etag = f"{tag}.evidence[{j}]"
            source = index.get(ev.source_id)
            if source is None:
                violations.append(
                    f"{etag}: unknown source_id '{ev.source_id}'")
                continue
            passage = source.get(ev.passage_id)
            if passage is None:
                violations.append(
                    f"{etag}: unknown passage_id '{ev.passage_id}' "
                    f"in source '{ev.source_id}'")
                continue
            if _norm(ev.quote) not in _norm(passage.text):
                violations.append(
                    f"{etag}: quote is not a verbatim substring of "
                    f"passage '{ev.passage_id}' — fabricated or altered citation")

    for sid in brief.sources_used:
        if sid not in index:
            violations.append(f"sources_used: unknown source_id '{sid}'")

    return ValidationReport(ok=not violations, violations=violations)
