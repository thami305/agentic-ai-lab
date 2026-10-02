"""Shared fixtures for Lab 9 tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from lab09.grader import StubGrader, load_calibration
from lab09.runner import load_golden, run_case

LAB09 = Path(__file__).resolve().parent.parent
GOLDEN = LAB09 / "data" / "golden.jsonl"
CALIBRATION = LAB09 / "data" / "calibration.jsonl"
THRESHOLDS = LAB09 / "eval" / "thresholds.json"


@pytest.fixture(scope="session")
def golden() -> list[dict]:
    return load_golden(GOLDEN)


@pytest.fixture(scope="session")
def by_id(golden) -> dict[str, dict]:
    return {c["id"]: c for c in golden}


@pytest.fixture(scope="session")
def calibration() -> list[dict]:
    return load_calibration(CALIBRATION)


@pytest.fixture()
def grader() -> StubGrader:
    return StubGrader()


@pytest.fixture()
def thresholds_path() -> Path:
    return THRESHOLDS
