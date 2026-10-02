"""Shared fixtures for Lab 4 tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab02.schemas import Packet
from lab03.policies import OraclePolicy
from lab03.state import BriefState
from lab04.checkpoint import CheckpointStore
from lab04.interrupt import build_interrupt_graph
from lab04.runner import run_persistent

DATA = Path(__file__).resolve().parent.parent / "data" / "packet.json"
QUESTION = "How utilized is Northwind's current warehouse?"


@pytest.fixture()
def packet() -> Packet:
    return Packet(**json.loads(DATA.read_text(encoding="utf-8")))


@pytest.fixture()
def store(tmp_path) -> CheckpointStore:
    return CheckpointStore(tmp_path / "checkpoints")


@pytest.fixture()
def paused(packet, store):
    """A run driven to the approval interrupt, with its checkpoint saved."""
    graph = build_interrupt_graph(OraclePolicy())
    state = BriefState(question=QUESTION, packet=packet)
    final = run_persistent(graph, state, store, "run-1")
    assert final.terminal == "await_approval"
    return final
