"""Base channel adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from proxi.gateway.events import GatewayEvent


class ChannelAdapter(ABC):
    """Parses one channel's wire format into a ``GatewayEvent``.

    Adapters know nothing about agents or sessions — that's the router's job.
    """

    source_id: str

    @abstractmethod
    async def parse(self, raw: dict) -> GatewayEvent | None:
        """Return None for non-actionable payloads (receipts, pings, etc.)."""
        ...
