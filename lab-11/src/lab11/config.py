"""Versioned service configuration with migration (rollback support).

Config files carry a ``version`` field. Loading an older version fills the
newer fields with defaults, so a previous-version config file still boots the
service — that is the rollback path: check out the old config, start the
service, keep serving.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

CURRENT_VERSION = 2


class ServiceConfig(BaseModel):
    """v2 is current. v1 only knew host/port/token."""

    version: int = CURRENT_VERSION
    host: str = "127.0.0.1"
    port: int = 8000
    token: str = "lab11-dev-token"  # override via config file or LAB11_TOKEN
    concurrency_limit: int = 2
    request_timeout_s: float = 30.0
    per_request_token_limit: int = 6000
    global_token_budget: int = 100_000
    idempotency_ttl_s: float = 3600.0
    packet_path: str | None = Field(
        default=None,
        description="Path to the lab-02 packet.json. None = lab-02's bundled packet.",
    )


def migrate_config(raw: dict) -> ServiceConfig:
    """Load any known config version, filling new fields with defaults."""
    data = dict(raw)
    version = data.get("version", 1)
    if version == 1:
        # v1 had no budgets, limits, or TTLs — defaults fill them in.
        data["version"] = CURRENT_VERSION
    elif version != CURRENT_VERSION:
        raise ValueError(f"unsupported config version: {version}")
    data.setdefault("version", CURRENT_VERSION)
    return ServiceConfig(**data)


def load_config(path: str | Path) -> ServiceConfig:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError("config file must contain a JSON object")
    return migrate_config(raw)
