"""Discord channel adapter and reply channel.

This adapter handles Discord interaction webhook payloads (not the bot
gateway WebSocket). It expects the Discord app to be configured with an
Interactions Endpoint URL pointing at ``/channels/discord/webhook``.
"""

from __future__ import annotations

import os

import httpx

from proxi.gateway.channels.base import ChannelAdapter
from proxi.gateway.events import GatewayEvent, ReplyChannel


class DiscordReplyChannel(ReplyChannel):
    source_type: str = "discord"  # type: ignore[assignment]

    async def send(self, text: str) -> None:
        token = os.environ.get("DISCORD_BOT_TOKEN", "")
        if not token:
            return
        # destination is channel_id for text channels
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"https://discord.com/api/v10/channels/{self.destination}/messages",
                headers={"Authorization": f"Bot {token}"},
                json={"content": text[:2000]},
            )


class DiscordAdapter(ChannelAdapter):
    source_id = "discord"

    async def parse(self, raw: dict) -> GatewayEvent | None:
        # Handle MESSAGE_CREATE style payloads forwarded by a relay bot
        content = raw.get("content")
        if not content:
            return None
        channel_id = raw.get("channel_id", "")
        return GatewayEvent(
            source_id=self.source_id,
            source_type="discord",
            payload={"text": content, "raw": raw},
            reply_channel=DiscordReplyChannel(destination=channel_id),
        )
