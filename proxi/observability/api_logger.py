"""API call logging for OpenAI and other providers."""

from typing import Any

from proxi.observability.logging import get_log_manager


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
        log_manager = get_log_manager()
        if not log_manager:
            return

        # Extract tool names only (not full definitions)
        tool_names = []
        if tools:
            for tool in tools:
                if isinstance(tool, dict):
                    tool_names.append(tool.get("name", "unknown"))

        request = {
            "model": model,
            "input": input_items,
            "tools": tool_names if tool_names else None,
            "prompt_cache_key": response_data.get("prompt_cache_key"),
        }

        response = {
            "content": response_data.get("output_text", ""),
            "usage": usage,
            "usage_raw": response_data.get("usage_raw"),
            "finish_reason": response_data.get("status"),
        }

        log_manager.log_api_call(
            method="responses.create",
            request=request,
            response=response,
        )
