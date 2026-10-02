"""The vendor proposal: the only ground truth the reviewers may cite.

A single synthetic proposal (data/proposal.txt) split into passages with
stable ids (PROP-P1 ... PROP-P9) and sections (Pricing / Terms /
Delivery/SLA). Passages are parsed from explicit `[passage <id> | section:
<name>]` markers so ids can never drift out of sync with the text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_MARKER = re.compile(
    r"\[passage\s+(PROP-P\d+)\s*\|\s*section:\s*([A-Za-z/]+)\s*\]")


@dataclass
class ProposalPassage:
    pid: str
    section: str
    text: str


@dataclass
class Proposal:
    passages: list[ProposalPassage] = field(default_factory=list)

    def by_id(self, pid: str) -> ProposalPassage | None:
        for p in self.passages:
            if p.pid == pid:
                return p
        return None

    def in_sections(self, *sections: str) -> list[ProposalPassage]:
        wanted = set(sections)
        return [p for p in self.passages if p.section in wanted]

    def word_count(self) -> int:
        return sum(len(p.text.split()) for p in self.passages)


@lru_cache(maxsize=8)
def load_proposal(path: str | Path | None = None) -> Proposal:
    raw = Path(path or DATA_DIR / "proposal.txt").read_text()
    matches = list(_MARKER.finditer(raw))
    if not matches:
        raise ValueError("no passage markers found in proposal text")
    passages: list[ProposalPassage] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        text = re.sub(r"\s+", " ", raw[start:end]).strip()
        passages.append(ProposalPassage(pid=m.group(1),
                                        section=m.group(2), text=text))
    return Proposal(passages=passages)
