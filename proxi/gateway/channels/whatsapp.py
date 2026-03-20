"""WhatsApp Cloud API channel adapter and reply channel."""

from __future__ import annotations

import os

import httpx

from proxi.gateway.channels.base import ChannelAdapter
from proxi.gateway.events import GatewayEvent, ReplyChannel


class WhatsAppReplyChannel(ReplyChannel):
    source_type: str = "whatsapp"  # type: ignore[assignment]

    async def send(self, text: str) -> None:
        token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        if not token or not phone_id:
            return
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"https://graph.facebook.com/v21.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": self.destination,
                    "type": "text",
                    "text": {"body": text},
                },
            )


class WhatsAppAdapter(ChannelAdapter):
    source_id = "whatsapp"

    async def parse(self, raw: dict) -> GatewayEvent | None:
        for entry in raw.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    from_number = msg.get("from", "")
                    body = msg.get("text", {}).get("body", "")
                    if not body:
                        continue
                    return GatewayEvent(
                        source_id=self.source_id,
                        source_type="whatsapp",
                        payload={"text": body, "raw": msg},
                        reply_channel=WhatsAppReplyChannel(destination=from_number),
                    )
        return None
