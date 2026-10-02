"""Shared fixtures for Lab 8 tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Defensive: the canonical run sets PYTHONPATH=src:../lab-02/src:../lab-03/src,
# but the tests also work with a bare `pytest` from the lab root.
_LAB_ROOT = Path(__file__).resolve().parent.parent
for _p in ("src",
           str((_LAB_ROOT / ".." / "lab-02" / "src").resolve()),
           str((_LAB_ROOT / ".." / "lab-03" / "src").resolve())):
    _d = str((_LAB_ROOT / _p).resolve()) if _p == "src" else _p
    if _d not in sys.path:
        sys.path.insert(0, _d)

from lab08.issues import ISSUES
from lab08.proposal import Proposal, load_proposal
from lab08.validate import verdict_for

LAB_ROOT = _LAB_ROOT


@pytest.fixture()
def proposal() -> Proposal:
    return load_proposal()


def review_payload_for(*issue_ids: str) -> dict:
    """A schema-valid Review dict built from catalog issues."""
    issues = [i for i in ISSUES if i.id in issue_ids]
    assert issues, f"unknown issue ids: {issue_ids}"
    return {
        "verdict": verdict_for(issues),
        "findings": [{"claim": i.claim, "severity": i.severity,
                      "evidence": {"passage_id": i.passage_id,
                                   "quote": i.quote}} for i in issues],
        "risks": [i.risk for i in issues],
    }
