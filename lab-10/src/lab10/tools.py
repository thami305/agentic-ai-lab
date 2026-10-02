"""Lab 10 tools — role-scoped registries and impact-tiered tools.

Impact tiers:
- low-impact (read-only): read_client, search_docs — analyst + admin.
- normal-impact (state-changing, low risk): update_client_note — analyst + admin.
- high-impact (external / irreversible): export_client_list (admin only),
  send_notification (analyst + admin), write_memory (analyst + admin, but
  consent-gated).

Every tool result carries `_ns` namespace markers so the NamespaceEnforcer
can verify that a run only ever sees its own client's data.

All tools are deterministic fakes over in-memory data — no network, no DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel

from .schemas import (ExportClientListArgs, OutageProbeArgs, ReadClientArgs,
                      SearchDocsArgs, SendNotificationArgs,
                      UpdateClientNoteArgs, WriteMemoryArgs)


class ToolOutageError(RuntimeError):
    """A tool (dependency) failed mid-run. The loop aborts bounded."""


@dataclass
class ToolDef:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[..., dict[str, Any]]
    roles: set[str] = field(default_factory=lambda: {"analyst", "admin"})
    impact: Literal["low", "normal", "high"] = "low"
    requires_approval: bool = False
    requires_consent: bool = False
    consent_scope: str = "memory"


class ToolRegistry:
    """The allow-list. Role scoping is enforced by the agent loop, which
    distinguishes 'unknown tool' from 'known but not permitted' for the
    audit trail."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDef]:
        return [self._tools[name] for name in sorted(self._tools)]

    def names(self) -> list[str]:
        return sorted(self._tools)


class SideEffectLog:
    """Records every side effect a tool actually performed.

    Tests assert on this: denied attacks must leave it empty, and an
    aborted run must show no writes past the abort point.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, tool: str, args: dict[str, Any]) -> None:
        self.entries.append({"tool": tool, "args": dict(args)})

    def for_tool(self, tool: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["tool"] == tool]

    def __len__(self) -> int:
        return len(self.entries)


class MemoryStore:
    """The agent's long-term memory. Written ONLY by write_memory, which
    the loop gates behind explicit user consent."""

    def __init__(self) -> None:
        self.facts: list[dict[str, Any]] = []

    def write(self, fact: str, scope: str) -> None:
        self.facts.append({"fact": fact, "scope": scope})

    def __len__(self) -> int:
        return len(self.facts)


CLIENTS = {
    "acme": {"id": "acme", "name": "Acme Corp", "tier": "enterprise"},
    "globex": {"id": "globex", "name": "Globex Inc", "tier": "growth"},
    "initech": {"id": "initech", "name": "Initech LLC", "tier": "startup"},
}


def build_registry(side_effects: SideEffectLog | None = None,
                   memory: MemoryStore | None = None,
                   extra: list[ToolDef] | None = None) -> ToolRegistry:
    # NB: `is None` checks, not `or` — empty logs are falsy via __len__.
    if side_effects is None:
        side_effects = SideEffectLog()
    if memory is None:
        memory = MemoryStore()

    def read_client(client_id: str) -> dict[str, Any]:
        client = CLIENTS.get(client_id)
        if client is None:
            return {"ok": False, "error": "unknown_client", "_ns": client_id}
        return {"ok": True, "client": {"_ns": client_id, **client}}

    def search_docs(client_id: str, query: str) -> dict[str, Any]:
        passages = [
            {"_ns": client_id, "doc": "contract-2026",
             "text": f"Standard terms for {client_id}: net-30 payment."},
            {"_ns": client_id, "doc": "policy-churn",
             "text": f"Churn review cadence for {client_id}: quarterly."},
        ]
        return {"ok": True, "query": query, "passages": passages}

    def export_client_list(client_id: str, format: str) -> dict[str, Any]:
        side_effects.record("export_client_list",
                            {"client_id": client_id, "format": format})
        return {"ok": True, "exported": 42, "format": format,
                "_ns": client_id}

    def send_notification(client_id: str, channel: str,
                          message: str) -> dict[str, Any]:
        side_effects.record("send_notification",
                            {"client_id": client_id, "channel": channel})
        return {"ok": True, "queued": True, "channel": channel,
                "_ns": client_id}

    def write_memory(fact: str, scope: str) -> dict[str, Any]:
        memory.write(fact, scope)
        side_effects.record("write_memory", {"scope": scope})
        return {"ok": True, "stored": True}

    def update_client_note(client_id: str, note: str) -> dict[str, Any]:
        side_effects.record("update_client_note", {"client_id": client_id})
        return {"ok": True, "note_id": "n1", "_ns": client_id}

    registry = ToolRegistry()
    registry.register(ToolDef(
        name="read_client",
        description="Read one client record. Low impact, read-only.",
        args_model=ReadClientArgs, fn=read_client, impact="low"))
    registry.register(ToolDef(
        name="search_docs",
        description="Search client documents. Low impact, read-only.",
        args_model=SearchDocsArgs, fn=search_docs, impact="low"))
    registry.register(ToolDef(
        name="update_client_note",
        description="Append a note to a client record. State-changing, low risk.",
        args_model=UpdateClientNoteArgs, fn=update_client_note,
        impact="normal"))
    registry.register(ToolDef(
        name="export_client_list",
        description="Export the full client list. HIGH IMPACT: admin only, "
                    "requires signed approval.",
        args_model=ExportClientListArgs, fn=export_client_list,
        roles={"admin"}, impact="high", requires_approval=True))
    registry.register(ToolDef(
        name="send_notification",
        description="Send an external notification. HIGH IMPACT: requires "
                    "signed approval.",
        args_model=SendNotificationArgs, fn=send_notification,
        impact="high", requires_approval=True))
    registry.register(ToolDef(
        name="write_memory",
        description="Write a fact to long-term memory. HIGH IMPACT: requires "
                    "explicit user consent (default deny).",
        args_model=WriteMemoryArgs, fn=write_memory,
        impact="high", requires_consent=True, consent_scope="memory"))
    for tool in extra or []:
        registry.register(tool)
    return registry
