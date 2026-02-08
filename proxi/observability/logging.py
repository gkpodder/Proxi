"""Structured logging setup."""

import logging
import sys
from pathlib import Path
from typing import Union

import structlog

# ANSI color codes for log categories
_RESET = "\033[0m"
_CATEGORY_COLORS = {
    "llm": "\033[36m",       # Cyan – LLM calls
    "tool": "\033[33m",      # Yellow – tool invocations
    "sub_agent": "\033[35m",  # Magenta – sub-agent invocations
    "mcp": "\033[32m",       # Green – MCP invocations
}

# Event name → category for colored prefix
_EVENT_CATEGORY_MAP = {
    # LLM
    "llm_call": "llm",
    "llm_call_stream": "llm",
    "llm_generate": "llm",
    "planner_decide": "llm",
    # Tool
    "tool_call": "tool",
    # Sub-agent
    "sub_agent_call": "sub_agent",
    "sub_agent_start": "sub_agent",
    "sub_agent_complete": "sub_agent",
    "sub_agent_timeout": "sub_agent",
    "sub_agent_error": "sub_agent",
}


def _event_category_processor(logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
    """Add _event_category and _event_color from event name for colored output."""
    event = event_dict.get("event", "")
    category = _EVENT_CATEGORY_MAP.get(event)
    if category is None and isinstance(event, str) and event.startswith("mcp_"):
        category = "mcp"
    event_dict["_event_category"] = category
    event_dict["_event_color"] = _CATEGORY_COLORS.get(
        category, "") if category else ""
    return event_dict


def _colored_console_renderer(logger: logging.Logger, method_name: str, event_dict: dict) -> str:
    """Render log line with a colored category tag prefix."""
    category = event_dict.get("_event_category")
    color = event_dict.get("_event_color", "")
    reset = _RESET

    # Pass a copy without our internal keys to ConsoleRenderer
    render_dict = {k: v for k, v in event_dict.items(
    ) if k not in ("_event_category", "_event_color")}

    tag = ""
    if category:
        labels = {"llm": "LLM", "tool": "TOOL",
                  "sub_agent": "SUB_AGENT", "mcp": "MCP"}
        tag = f"{color}[{labels.get(category, category.upper())}]{reset} "

    # Compact format: no level padding, minimal event padding
    console_renderer = structlog.dev.ConsoleRenderer(
        pad_level=False,
        pad_event_to=0,
    )
    line = console_renderer(logger, method_name, render_dict)
    return tag + line


def _plain_console_renderer(logger: logging.Logger, method_name: str, event_dict: dict) -> str:
    """Render log line with plain [CATEGORY] tag for log files (no ANSI)."""
    category = event_dict.get("_event_category")
    render_dict = {k: v for k, v in event_dict.items()
                   if k not in ("_event_category", "_event_color")}
    tag = ""
    if category:
        labels = {"llm": "LLM", "tool": "TOOL",
                  "sub_agent": "SUB_AGENT", "mcp": "MCP"}
        tag = f"[{labels.get(category, category.upper())}] "
    console_renderer = structlog.dev.ConsoleRenderer(
        pad_level=False,
        pad_event_to=0,
        colors=False,
    )
    line = console_renderer(logger, method_name, render_dict)
    return tag + line


def setup_logging(
    level: str = "INFO",
    use_colors: bool = True,
    log_file: Union[str, Path, None] = None,
) -> None:
    """Set up structured logging with optional category colors and optional log file."""
    stream = sys.stdout
    if log_file is not None:
        path = Path(log_file).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(path, "a", encoding="utf-8")
        # Keep colors so tail -f logs/proxi.log shows colored output in the terminal
        use_colors = True

    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=getattr(logging, level.upper()),
    )

    if use_colors:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            _event_category_processor,
            _colored_console_renderer,
        ]
    else:
        # Plain format when explicitly requested (no ANSI)
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            _event_category_processor,
            _plain_console_renderer,
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger."""
    return structlog.get_logger(name)
