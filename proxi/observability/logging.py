"""Structured logging setup."""

import atexit
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Union

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
    """Render log line with [timestamp] [event] [level] and key=value pairs."""
    color = event_dict.get("_event_color", "")
    event = event_dict.get("event", "")
    level = event_dict.get("_level", "INFO").upper()
    reset = _RESET

    # Clean dict - remove internal fields and level
    render_dict = {k: v for k, v in event_dict.items()
                   if k not in ("_event_category", "_event_color", "_level", "event", "level")}

    # Get current timestamp
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Build: [timestamp] [event] [level]
    event_tag = ""
    if event:
        if color:
            event_tag = f" {color}[{event.upper()}]{reset}"
        else:
            event_tag = f" [{event.upper()}]"
    
    prefix = f"[{ts}]{event_tag} [{level}]"

    # Format all key=value pairs
    parts = []
    for k, v in render_dict.items():
        parts.append(f"{k}={v}")
    
    line = " ".join(parts) if parts else ""
    return prefix + (" " + line if line else "")


def _plain_console_renderer(logger: logging.Logger, method_name: str, event_dict: dict) -> str:
    """Render log line with [timestamp] [event] [level] and key=value pairs."""
    event = event_dict.get("event", "")
    level = event_dict.get("_level", "INFO").upper()
    
    # Clean dict - remove internal fields and level
    render_dict = {k: v for k, v in event_dict.items()
                   if k not in ("_event_category", "_event_color", "_level", "event", "level")}
    
    # Get current timestamp
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Build: [timestamp] [event] [level]
    event_tag = ""
    if event:
        event_tag = f" [{event.upper()}]"
    
    prefix = f"[{ts}]{event_tag} [{level}]"
    
    # Format all key=value pairs
    parts = []
    for k, v in render_dict.items():
        parts.append(f"{k}={v}")
    
    line = " ".join(parts) if parts else ""
    return prefix + (" " + line if line else "")


def setup_logging(
    level: str = "INFO",
    use_colors: bool = True,
    log_file: Union[str, Path, None] = None,
) -> None:
    """Set up structured logging with optional category colors and optional log file.
    
    When log_file is provided:
    - Console output (stdout) will have ANSI colors
    - File output will be plain text without ANSI codes
    """
    # Configure base logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    # Console processors (with colors)
    console_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        _event_category_processor,
        _colored_console_renderer,
    ]

    # File processors (without colors)
    file_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        _event_category_processor,
        _plain_console_renderer,
    ]

    if log_file is None:
        # Only console output
        processors = console_processors
        logger_factory = structlog.PrintLoggerFactory(file=sys.stdout)
    else:
        # Both console and file output
        path = Path(log_file).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create a combined logger factory that writes to both stdout and file
        class DualOutputFactory:
            """Logger factory that writes to both stdout (colored) and file (plain)."""
            
            def __init__(self, file_path: Path):
                self.file_path = file_path
                self.file_handle = open(file_path, "a", encoding="utf-8")
                atexit.register(self._cleanup)
            
            def _cleanup(self) -> None:
                try:
                    self.file_handle.close()
                except Exception:
                    pass
            
            def __call__(self, file=None):
                """Return a logger that writes to both console and file."""
                # Create separate loggers for console and file
                console_logger = structlog.PrintLoggerFactory(file=sys.stdout)
                file_logger = structlog.PrintLoggerFactory(file=self.file_handle)
                
                class DualLogger:
                    def msg(self, message: str) -> str:
                        # Write to console (will use colored processor)
                        return message
                    
                    def __call__(self, message: str) -> str:
                        # This gets called after processing
                        # Write to both outputs
                        print(message, file=sys.stdout)
                        # Also write to file
                        self.file_handle.write(message + "\n")
                        self.file_handle.flush()
                        return message
                
                dual = DualLogger()
                dual.file_handle = self.file_handle
                return dual
        
        # Simpler approach: use two separate processor chains
        # Console: colored output
        # File: plain text output
        
        # We'll handle this by creating a custom processor that logs to file
        class FileOutputProcessor:
            """Logs output to file without ANSI codes."""
            
            def __init__(self, file_path: Path):
                self.file_path = file_path
                self.file_handle = open(file_path, "a", encoding="utf-8")
                atexit.register(self._cleanup)
            
            def _cleanup(self) -> None:
                try:
                    self.file_handle.close()
                except Exception:
                    pass
            
            def __call__(self, logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
                # Render using the same plain renderer
                message = _plain_console_renderer(logger, method_name, event_dict)
                
                # Write to file
                self.file_handle.write(message + "\n")
                self.file_handle.flush()
                
                # Return the event_dict unchanged so it gets rendered to console
                return event_dict
        
        file_processor = FileOutputProcessor(path)
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            _event_category_processor,
            file_processor,  # Handle file logging before console rendering
            _colored_console_renderer,
        ]
        logger_factory = structlog.PrintLoggerFactory(file=sys.stdout)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger."""
    return structlog.get_logger(name)


# Global log manager instance
_global_log_manager: "LogManager | None" = None


class LogManager:
    """Manages timestamped log directories and API call logging."""

    def __init__(self, base_dir: Union[str, Path] = "logs", session_id: str | None = None):
        """Initialize log manager with base directory and optional session ID."""
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Create timestamped directory: YYYYMMDD_HHMMSS
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = session_id or timestamp
        self.session_dir = self.base_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Log files
        self.log_file = self.session_dir / "proxi.log"
        self.api_log_file = self.session_dir / "api_calls.json"
        
        # Set up file handles
        self._log_stream: Any = open(self.log_file, "w", encoding="utf-8")
        atexit.register(self._cleanup)
        
    def _cleanup(self) -> None:
        """Clean up file handles."""
        if hasattr(self, "_log_stream") and self._log_stream:
            try:
                self._log_stream.close()
            except Exception:
                pass

    def get_session_dir(self) -> Path:
        """Get the session directory path."""
        return self.session_dir

    def get_log_file(self) -> Path:
        """Get the main log file path."""
        return self.log_file

    def get_api_log_file(self) -> Path:
        """Get the API calls log file path."""
        return self.api_log_file

    def log_api_call(self, method: str, request: dict[str, Any], response: dict[str, Any]) -> None:
        """Log an API call to the JSON api log file with nice formatting."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "request": request,
            "response": response,
        }
        try:
            with open(self.api_log_file, "a", encoding="utf-8") as f:
                # Pretty-print with indentation for readability
                f.write(json.dumps(entry, indent=2) + "\n\n")
        except Exception as e:
            get_logger(__name__).error("failed_to_log_api_call", error=str(e))

    def configure_logging(self, level: str = "INFO", use_colors: bool = True) -> None:
        """Configure structlog to use this manager's log file."""
        setup_logging(
            level=level,
            use_colors=use_colors,
            log_file=self.log_file,
        )


def init_log_manager(
    base_dir: Union[str, Path] = "logs",
    session_id: str | None = None,
) -> LogManager:
    """Initialize the global log manager."""
    global _global_log_manager
    _global_log_manager = LogManager(base_dir=base_dir, session_id=session_id)
    return _global_log_manager


def get_log_manager() -> LogManager | None:
    """Get the global log manager."""
    return _global_log_manager
