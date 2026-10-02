"""Shared fixtures for Lab 3 tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from lab02.packet import load_packet
from lab02.schemas import Packet
from lab03.nodes import build_graph
from lab03.graph import Graph
from lab03.state import BriefState

DATA = Path(__file__).resolve().parent.parent / "data" / "packet.json"


@pytest.fixture()
def packet() -> Packet:
    return load_packet(DATA)


@pytest.fixture()
def graph(packet) -> Graph:
    return build_graph()


def run_question(graph: Graph, packet: Packet, question: str) -> BriefState:
    state = BriefState(question=question, packet=packet)
    return graph.run(state)
