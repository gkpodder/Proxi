"""API call logging for OpenAI and other providers."""

import json
import os
from typing import Any

from proxi.observability.logging import get_log_manager
from proxi.observability.perf import elapsed_ms, emit_perf, now_ns


class OpenAIAPILogger:
    """Logger for OpenAI API calls."""

    def log_response(
        self,
        model: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response_data: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        """Log a Responses API call with clean, readable output."""
        start_ns = now_ns()
        log_manager = get_log_manager()
        if not log_manager:
            return

        max_chars = int(os.getenv("PROXI_API_LOG_MAX_CHARS", "4000"))

        def _truncate(value: Any) -> Any:
            if isinstance(value, str) and len(value) > max_chars:
                return value[:max_chars] + "...<truncated>"
            if isinstance(value, list):
                return [_truncate(v) for v in value]
            if isinstance(value, dict):
                return {k: _truncate(v) for k, v in value.items()}
            return value

        # Extract tool names only (not full definitions)
        tool_names = []
        if tools:
            for tool in tools:
                if isinstance(tool, dict):
                    tool_names.append(tool.get("name", "unknown"))

        request = {
            "model": model,
            "input": _truncate(input_items),
            "tools": tool_names if tool_names else None,
            "prompt_cache_key": response_data.get("prompt_cache_key"),
        }

        response = {
            "content": _truncate(response_data.get("output_text", "")),
            "usage": usage,
            "usage_raw": _truncate(response_data.get("usage_raw")),
            "finish_reason": response_data.get("status"),
        }

        log_manager.log_api_call(
            method="responses.create",
            request=request,
            response=response,
        )
        emit_perf(
            "perf_api_log",
            method="responses.create",
            request_bytes=len(json.dumps(request, separators=(",", ":")).encode("utf-8")),
            response_bytes=len(json.dumps(response, separators=(",", ":")).encode("utf-8")),
            elapsed_ms=round(elapsed_ms(start_ns), 3),
        )
