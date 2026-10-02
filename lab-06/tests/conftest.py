"""Shared fixtures for lab-06 tests."""

import pytest

from lab06.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json")


@pytest.fixture
def now():
    return 1_700_000_000.0
