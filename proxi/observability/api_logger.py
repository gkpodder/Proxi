"""API call logging for OpenAI and other providers."""

from typing import Any

from proxi.observability.logging import get_log_manager


class OpenAIAPILogger:
    """Logger for OpenAI API calls."""

    def log_chat_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response_data: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        """Log a chat completion API call with clean, readable output."""
        log_manager = get_log_manager()
        if not log_manager:
            return

        # Clean request: extract just what's needed
        clean_messages = []
        for msg in messages:
            clean_msg = {
                "role": msg.get("role"),
                "content": msg.get("content", ""),
            }
            clean_messages.append(clean_msg)

        # Extract tool names only (not full definitions)
        tool_names = []
        if tools:
            for tool in tools:
                if isinstance(tool, dict) and "function" in tool:
                    tool_names.append(tool["function"].get("name", "unknown"))

        request = {
            "model": model,
            "messages": clean_messages,
            "tools": tool_names if tool_names else None,
        }

        # Extract response content cleanly
        choices = response_data.get("choices", [])
        response_content = ""
        if choices and isinstance(choices, list):
            msg = choices[0].get("message", {})
            response_content = msg.get("content", "")

        response = {
            "content": response_content,
            "usage": usage,
            "finish_reason": response_data.get("finish_reason"),
        }

        log_manager.log_api_call(
            method="chat.completions.create",
            request=request,
            response=response,
        )
