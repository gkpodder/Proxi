"""Cron source — fires events on APScheduler cron triggers."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from proxi.gateway.config import GatewayConfig, SourceConfig
from proxi.gateway.events import GatewayEvent
from proxi.gateway.lanes.manager import LaneManager
from proxi.gateway.router import EventRouter
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


def _parse_cron(expr: str) -> dict[str, str]:
    """Convert a five-field cron expression into APScheduler keyword args.

    Format: ``minute hour day month day_of_week``
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {expr!r}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


class CronRegistry:
    def __init__(
        self,
        config: GatewayConfig,
        lane_manager: LaneManager,
        router: EventRouter,
    ) -> None:
        self._config = config
        self._lm = lane_manager
        self._router = router

    def load_all(self, scheduler: AsyncIOScheduler) -> None:
        for source_id, source in self._config.sources.items():
            if source.source_type != "cron":
                continue
            try:
                cron_fields = _parse_cron(source.schedule)
            except ValueError as exc:
                logger.error("cron_parse_error", source=source_id, error=str(exc))
                continue
            scheduler.add_job(
                self._fire,
                "cron",
                args=[source],
                id=source_id,
                replace_existing=True,
                **cron_fields,
            )
            logger.info("cron_job_registered", source=source_id, schedule=source.schedule)

    async def _fire(self, source: SourceConfig) -> None:
        event = GatewayEvent(
            source_id=source.source_id,
            source_type="cron",
            payload={"text": source.prompt},
            reply_channel=None,
            priority=source.priority,
        )
        event.session_id = self._router.resolve(event)
        logger.info("cron_fired", source=source.source_id, session=event.session_id)
        await self._lm.route(event)
