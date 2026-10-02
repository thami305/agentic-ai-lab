"""Shared fixtures for Lab 2 tests."""
from __future__ import annotations

import pytest

from lab02.agent import Agent
from lab02.models import OracleStub, PromptOnlyStub
from lab02.packet import load_packet
from lab02.schemas import Packet
from lab02.tools import ToolRegistry, build_registry


@pytest.fixture()
def packet() -> Packet:
    return load_packet()


@pytest.fixture()
def registry(packet) -> ToolRegistry:
    return build_registry(packet)


@pytest.fixture()
def tool_agent(packet, registry) -> Agent:
    return Agent(OracleStub(), registry, packet)


@pytest.fixture()
def prompt_agent(packet) -> Agent:
    from lab02.agent import PROMPT_ONLY_SYSTEM
    return Agent(PromptOnlyStub(), ToolRegistry(), packet,
                 system_prompt=PROMPT_ONLY_SYSTEM)
