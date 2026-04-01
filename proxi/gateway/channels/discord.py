"""Discord channel adapter and reply channel.

This adapter handles Discord interaction webhook payloads (not the bot
gateway WebSocket). It expects the Discord app to be configured with an
Interactions Endpoint URL pointing at ``/channels/discord/webhook``.
"""

from __future__ import annotations

import os
from typing import Any

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

    def __init__(self, *, command_prefix: str = "/proxi", allow_plain: bool = False) -> None:
        self._command_prefix = (command_prefix or "/proxi").strip() or "/proxi"
        self._allow_plain = bool(allow_plain)

    def _parse_command(self, text: str) -> dict[str, Any] | None:
        content = text.strip()
        if not content:
            return None

        if content.startswith(self._command_prefix):
            remainder = content[len(self._command_prefix):].strip()
            if not remainder:
                return {"action": "help"}

            parts = remainder.split(maxsplit=1)
            verb = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if verb in {"help", "?"}:
                return {"action": "help"}
            if verb in {"abort", "stop", "cancel"}:
                return {"action": "abort"}
            if verb == "status":
                return {"action": "status"}
            if verb == "switch":
                if not arg:
                    return {"action": "help", "error": "switch requires an agent id"}
                return {"action": "switch", "agent_id": arg}

            task = remainder
            return {"action": "start", "task": task}

        if self._allow_plain:
            return {"action": "start", "task": content}

        return None

    async def parse(self, raw: dict) -> GatewayEvent | None:
        # Handle MESSAGE_CREATE style payloads forwarded by a relay bot
        content = str(raw.get("content", "")).strip()
        if not content:
            return None

        command = self._parse_command(content)
        if command is None:
            return None

        channel_id = str(raw.get("channel_id") or raw.get("channel", {}).get("id") or "").strip()
        author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
        user_id = str(author.get("id", "")).strip()

        payload: dict[str, Any] = {
            "raw": raw,
            "command": command,
            "channel_id": channel_id,
            "user_id": user_id,
        }
        if command.get("action") == "start":
            payload["text"] = str(command.get("task", "")).strip()

        return GatewayEvent(
            source_id=self.source_id,
            source_type="discord",
            payload=payload,
            reply_channel=DiscordReplyChannel(destination=channel_id),
        )
