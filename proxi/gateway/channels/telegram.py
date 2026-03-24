"""Telegram channel adapter and reply channel."""

from __future__ import annotations

import os

import httpx

from proxi.gateway.channels.base import ChannelAdapter
from proxi.gateway.events import GatewayEvent, ReplyChannel


class TelegramReplyChannel(ReplyChannel):
    source_type: str = "telegram"  # type: ignore[assignment]

    async def send(self, text: str) -> None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return
        # Telegram limits messages to 4096 chars; chunk if needed
        chunks = [text[i : i + 4096] for i in range(0, len(text), 4096)]
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": self.destination,
                        "text": chunk,
                        "parse_mode": "Markdown",
                    },
                )


class TelegramAdapter(ChannelAdapter):
    source_id = "telegram"

    async def parse(self, raw: dict) -> GatewayEvent | None:
        msg = raw.get("message")
        if not msg:
            return None
        text = msg.get("text")
        if not text:
            return None
        chat_id = str(msg["chat"]["id"])
        return GatewayEvent(
            source_id=self.source_id,
            source_type="telegram",
            payload={"text": text, "raw": msg},
            reply_channel=TelegramReplyChannel(destination=chat_id),
        )
