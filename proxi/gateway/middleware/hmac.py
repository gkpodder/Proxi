"""HMAC-SHA256 webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, Request

from proxi.gateway.config import SourceConfig


async def verify_telegram_signature(request: Request) -> None:
    """Check the ``X-Telegram-Bot-Api-Secret-Token`` header.

    The expected value is the ``TELEGRAM_WEBHOOK_SECRET`` env var set during
    webhook registration via ``setWebhook``.
    """
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected:
        return
    actual = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(actual, expected):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")


async def verify_whatsapp_signature(request: Request) -> None:
    """Validate ``X-Hub-Signature-256`` using ``WHATSAPP_APP_SECRET``."""
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret:
        return
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Missing HMAC signature")

    body = await request.body()
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature_header, expected):
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")


async def verify_webhook_hmac(request: Request, source: SourceConfig) -> None:
    """Generic HMAC-SHA256 verification for inbound webhooks.

    The secret is read from the environment variable named by
    ``source.secret_env``. The signature is expected in the
    ``X-Signature-256`` header.
    """
    if not source.secret_env:
        raise HTTPException(status_code=403, detail="Webhook secret_env is required")
    secret = os.environ.get(source.secret_env, "")
    if not secret:
        raise HTTPException(
            status_code=403,
            detail=f"Webhook secret environment variable {source.secret_env!r} is not set",
        )

    signature_header = request.headers.get("X-Signature-256", "")
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Missing webhook signature")

    body = await request.body()
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature_header, expected):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
