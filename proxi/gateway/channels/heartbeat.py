"""Heartbeat source — periodic interval-based event injection."""

from __future__ import annotations

import asyncio

from proxi.gateway.config import GatewayConfig, SourceConfig
from proxi.gateway.events import GatewayEvent
from proxi.gateway.lanes.manager import LaneManager
from proxi.gateway.router import EventRouter
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class HeartbeatManager:
    def __init__(
        self,
        config: GatewayConfig,
        lane_manager: LaneManager,
        router: EventRouter,
    ) -> None:
        self._config = config
        self._lm = lane_manager
        self._router = router
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        for source_id, source in self._config.sources.items():
            if source.source_type != "heartbeat":
                continue
            if source.interval <= 0:
                logger.warning("heartbeat_invalid_interval", source=source_id)
                continue
            task = asyncio.create_task(
                self._loop(source), name=f"heartbeat:{source_id}"
            )
            self._tasks.append(task)
            logger.info(
                "heartbeat_started", source=source_id, interval=source.interval
            )

    async def _loop(self, source: SourceConfig) -> None:
        while True:
            await asyncio.sleep(source.interval)
            event = GatewayEvent(
                source_id=source.source_id,
                source_type="heartbeat",
                payload={"text": source.prompt},
                priority=source.priority,
            )
            event.session_id = self._router.resolve(event)
            logger.debug("heartbeat_fired", source=source.source_id)
            await self._lm.route(event)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
