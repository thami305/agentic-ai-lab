"""Read-only tools + registry for Lab 1.

Design rules:
- Every tool opens its own read-only SQLite connection (mode=ro + query_only).
- Arguments are validated against a Pydantic model BEFORE the function runs.
- Unknown tools are never executed: the registry is the allow-list.
- Money and math happen here, deterministically — never in the model.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .schemas import CalculateMetricArgs, GetClientArgs, ListDealsArgs

CLOSED_STAGES = ("closed_won", "closed_lost")


@dataclass
class ToolDef:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[..., dict[str, Any]]
    timeout_s: float = 5.0
    max_retries: int = 2
    read_only: bool = True


class ToolRegistry:
    """The allow-list. If a tool is not registered here, it does not run."""

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


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def build_registry(db_path: str | Path, extra: list[ToolDef] | None = None) -> ToolRegistry:
    """Build the Lab 1 registry: three read-only tools over the pipeline DB."""
    db_path = Path(db_path)

    def get_client(client_id: str) -> dict[str, Any]:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM clients WHERE LOWER(id) = LOWER(?)", (client_id,)
            ).fetchone()
        if row is None:
            return {"ok": False, "error": "unknown_client",
                    "detail": f"No client with id '{client_id}'."}
        return {"ok": True, "client": dict(row)}

    def list_deals(client_id: str | None = None, stage: str | None = None,
                   limit: int = 50) -> dict[str, Any]:
        clauses, params = [], []
        if client_id:
            clauses.append("LOWER(client_id) = LOWER(?)")
            params.append(client_id)
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM deals {where} ORDER BY value DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return {"ok": True, "count": len(rows), "deals": [dict(r) for r in rows]}

    def calculate_metric(metric: str, client_id: str | None = None,
                         stage: str | None = None) -> dict[str, Any]:
        clauses, params = [], []
        if client_id:
            clauses.append("LOWER(client_id) = LOWER(?)")
            params.append(client_id)
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(db_path) as conn:
            rows = [dict(r) for r in
                    conn.execute(f"SELECT * FROM deals {where}", params).fetchall()]
        scope = {"client_id": client_id, "stage": stage}
        if metric == "win_rate":
            closed = [r for r in rows if r["stage"] in CLOSED_STAGES]
            if not closed:
                return {"ok": False, "error": "no_data",
                        "detail": "No closed deals in scope.", "scope": scope}
            won = [r for r in closed if r["stage"] == "closed_won"]
            return {"ok": True, "metric": metric, "value": len(won) / len(closed),
                    "basis": {"won": len(won), "lost": len(closed) - len(won)},
                    "scope": scope}
        open_rows = [r for r in rows if r["stage"] not in CLOSED_STAGES]
        if not open_rows:
            return {"ok": False, "error": "no_data",
                    "detail": "No open deals in scope.", "scope": scope}
        if metric == "weighted_pipeline":
            value = sum(r["value"] * r["probability"] for r in open_rows)
        elif metric == "total_pipeline":
            value = sum(r["value"] for r in open_rows)
        elif metric == "avg_deal_size":
            value = sum(r["value"] for r in open_rows) / len(open_rows)
        else:  # unreachable: schema validates the literal, kept as a backstop
            return {"ok": False, "error": "unknown_metric",
                    "detail": f"Unknown metric '{metric}'.", "scope": scope}
        return {"ok": True, "metric": metric, "value": value,
                "basis": {"deals": len(open_rows)}, "scope": scope}

    registry = ToolRegistry()
    registry.register(ToolDef(
        name="get_client",
        description="Fetch one client record by id. Returns unknown_client when the id does not exist.",
        args_model=GetClientArgs, fn=get_client))
    registry.register(ToolDef(
        name="list_deals",
        description="List deals, optionally filtered by client_id and/or stage. Read-only.",
        args_model=ListDealsArgs, fn=list_deals))
    registry.register(ToolDef(
        name="calculate_metric",
        description="Deterministically compute weighted_pipeline, total_pipeline, avg_deal_size, or win_rate over the deals in scope.",
        args_model=CalculateMetricArgs, fn=calculate_metric))
    for tool in extra or []:
        registry.register(tool)
    return registry
