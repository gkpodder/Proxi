"""Core event schema and reply channel abstraction for the gateway."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal[
    "telegram", "whatsapp", "discord", "http", "cron", "heartbeat", "webhook"
]


class ReplyChannel(BaseModel):
    """Abstract destination for sending agent output back to the originating source."""

    source_type: SourceType
    destination: str

    async def send(self, text: str) -> None:
        raise NotImplementedError

    model_config = {"arbitrary_types_allowed": True}


class GatewayEvent(BaseModel):
    """Normalised event that flows through the gateway pipeline.

    Adapters set everything except ``session_id``.
    The ``EventRouter`` stamps ``session_id``.
    The lane never touches origin fields.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    source_type: SourceType
    payload: dict[str, Any] = Field(default_factory=dict)
    reply_channel: Optional[ReplyChannel] = None
    broadcast_reply_channels: list[ReplyChannel] = Field(default_factory=list)
    session_id: str = ""
    priority: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"arbitrary_types_allowed": True}
