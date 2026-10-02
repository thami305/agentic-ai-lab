"""Bearer-token auth. One shared secret, constant-time compare."""
from __future__ import annotations

import hmac


def check_bearer(authorization: str | None, expected: str) -> bool:
    """True iff the Authorization header is exactly ``Bearer <expected>``."""
    if not authorization:
        return False
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    return hmac.compare_digest(presented, expected)
