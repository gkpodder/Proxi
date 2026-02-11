"""Tracing for agent execution."""

from typing import Any

from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class TraceContext:
    """Context manager for tracing agent operations."""

    def __init__(self, operation: str, **kwargs: Any):
        """Initialize trace context."""
        self.operation = operation
        self.kwargs = kwargs
        self.logger = logger.bind(operation=operation, **kwargs)

    def __enter__(self):
        """Enter trace context."""
        self.logger.info("trace_start")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit trace context."""
        if exc_type is not None:
            self.logger.error(
                "trace_error",
                exc_type=exc_type.__name__ if exc_type else None,
                exc_val=str(exc_val) if exc_val else None,
            )
        else:
            self.logger.info("trace_end")
        return False
