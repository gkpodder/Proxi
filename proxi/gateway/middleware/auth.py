"""Bearer-token authentication middleware for direct HTTP invocation."""

from __future__ import annotations

from fastapi import Request, HTTPException

from proxi.security.key_store import get_key_value


async def verify_bearer_token(request: Request) -> None:
    """Validate ``Authorization: Bearer <token>`` against the key store.

    The expected token is stored as ``GATEWAY_API_TOKEN`` in keys.db.
    If the key is not configured, auth is disabled (open access).
    """
    expected = get_key_value("GATEWAY_API_TOKEN")
    if not expected:
        return  # auth not configured — allow all

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = auth_header[7:]
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid token")
