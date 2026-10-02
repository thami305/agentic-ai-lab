"""Role-based authorization for Lab 7.

The current role lives in a contextvar — the production mechanism (an auth
layer would set it per request). Tests set it before entering the in-memory
transport: InMemoryTransport starts the server in a child task that
snapshots the caller's context at transport entry, so a role set before
that point is visible server-side for the whole session.
"""

from contextvars import ContextVar

from .errors import ErrorCode, Lab7Error

current_role: ContextVar[str | None] = ContextVar("lab07_current_role", default=None)

ROLE_ANALYST = "analyst"
ROLE_VIEWER = "viewer"


def get_role() -> str | None:
    return current_role.get()


def require_role(role: str, *, capability: str) -> None:
    """Enforce the per-capability policy server-side.

    Raises Lab7Error(UNAUTHORIZED) before any data is touched, so an
    unauthorized caller gets an explicit error and no data.
    """
    actual = get_role()
    if actual != role:
        raise Lab7Error(
            ErrorCode.UNAUTHORIZED,
            f"role {actual!r} is not permitted to use {capability}; requires role {role!r}",
        )
