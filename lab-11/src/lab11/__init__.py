"""Lab 11 — the lab-02 brief pipeline as a production-shaped HTTP service.

Stdlib ``http.server`` only. The model proposes; deterministic code decides —
and now that code runs behind auth, idempotency keys, budgets, a kill switch,
and durable state.
"""

from .config import ServiceConfig, load_config
from .server import App, make_server

__all__ = ["App", "ServiceConfig", "load_config", "make_server"]
