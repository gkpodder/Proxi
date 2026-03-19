"""Lightweight performance instrumentation helpers."""

from __future__ import annotations

import os
import time
from typing import Any

from proxi.observability.logging import get_logger

logger = get_logger(__name__)


def perf_enabled() -> bool:
    """Check whether performance instrumentation is enabled."""
    value = os.getenv("PROXI_PERF_ENABLED", "0").strip().lower()
    return value not in {"0", "false", "no", "off"}


def now_ns() -> int:
    """Fast monotonic timestamp."""
    return time.perf_counter_ns()


def elapsed_ms(start_ns: int, end_ns: int | None = None) -> float:
    """Elapsed milliseconds from perf counter ns values."""
    stop = now_ns() if end_ns is None else end_ns
    return (stop - start_ns) / 1_000_000.0


def emit_perf(event: str, **fields: Any) -> None:
    """Emit a structured performance event."""
    if not perf_enabled():
        return
    logger.info(event, **fields)
