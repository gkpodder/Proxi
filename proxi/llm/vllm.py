"""vLLM LLM client implementation using the OpenAI-compatible Chat Completions API."""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from openai import AsyncOpenAI

from proxi.core.state import Message
from proxi.llm.schemas import ModelDecision, ModelResponse, SubAgentCall, SubAgentSpec, ToolCall, ToolSpec
from proxi.observability.api_logger import OpenAIAPILogger
from proxi.observability.logging import get_logger

logger = get_logger(__name__)
api_logger = OpenAIAPILogger()


class VLLMClient:
    """vLLM client using the OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "http://localhost:8000/v1",
        model: str = "local",
    ):
        """Initialize vLLM client.

        Args:
            api_key: Bearer token for vLLM auth. Defaults to "dummy" (vLLM may run without auth).
            base_url: Base URL of the vLLM server, e.g. http://localhost:8000/v1.
            model: Name of the served model as reported by vLLM.
        """
        self.client = AsyncOpenAI(api_key=api_key or "dummy", base_url=base_url)
        self.base_url = base_url
        self.model = model
        self.logger = logger

    # ------------------------------------------------------------------
    # Message / tool conversion
    # ------------------------------------------------------------------

    def _message_text(self, msg: Message) -> str:
        return msg.content if msg.content is not None else ""

    def _convert_messages(self, messages: Sequence[Message]) -> list[dict[str, Any]]:
        """Convert internal messages to Chat Completions format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "content": self._message_text(msg),
                    }
                )
                continue

            if msg.tool_calls:
                tc_list: list[dict[str, Any]] = []
                for tc in msg.tool_calls:
                    function = tc.get("function", {}) if isinstance(tc, dict) else {}
                    arguments = function.get("arguments", "{}")
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments)
                    tc_list.append(
                        {
                            "id": tc.get("id", "") if isinstance(tc, dict) else "",
                            "type": "function",
                            "function": {
                                "name": function.get("name", ""),
                                "arguments": arguments,
                            },
                        }
                    )
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": tc_list,
                }
                result.append(entry)
                continue

            role = msg.role if msg.role in {"user", "assistant", "system"} else "user"
            result.append({"role": role, "content": self._message_text(msg)})
        return result

    def _convert_tools(self, tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        """Convert tool specs to Chat Completions function tool format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in sorted(tools, key=lambda t: t.name)
        ]

    def _convert_agents_to_tools(self, agents: Sequence[SubAgentSpec] | None) -> list[dict[str, Any]]:
        """Represent sub-agents as callable function tools."""
        if not agents:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": f"sub_agent_{agent.name}",
                    "description": f"[Sub-Agent] {agent.description}",
                    "parameters": agent.input_schema,
                },
            }
            for agent in sorted(agents, key=lambda a: a.name)
        ]

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------

    def _extract_tool_calls_from_message(self, raw_tool_calls: Any) -> list[dict[str, Any]]:
        """Normalise tool_calls from a Chat Completions message object."""
        result: list[dict[str, Any]] = []
        for tc in raw_tool_calls or []:
            if isinstance(tc, dict):
                result.append(tc)
            else:
                fn = getattr(tc, "function", None)
                arguments = getattr(fn, "arguments", "{}") if fn else "{}"
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments)
                result.append(
                    {
                        "id": getattr(tc, "id", ""),
                        "type": "function",
                        "function": {
                            "name": getattr(fn, "name", "") if fn else "",
                            "arguments": arguments,
                        },
                    }
                )
        return result

    def _build_usage(self, usage_obj: Any) -> dict[str, Any]:
        """Build normalised usage dict from a Chat Completions usage object."""
        prompt_tokens = getattr(usage_obj, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage_obj, "completion_tokens", 0) or 0
        total_tokens = getattr(usage_obj, "total_tokens", None)
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        result: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        # vLLM exposes cached tokens via prompt_tokens_details when APC is active.
        details = getattr(usage_obj, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", None)
            if cached is not None:
                result["prompt_tokens_details"] = {"cached_tokens": cached}
                result["cache_hit"] = cached > 0
        return result

    def _build_decision(self, content: str, tool_calls: list[dict[str, Any]]) -> ModelDecision:
        """Build a provider-agnostic decision object."""
        if not tool_calls:
            return ModelDecision.respond(content=content, reasoning=None)

        first_call = tool_calls[0]
        tool_name = first_call.get("function", {}).get("name", "")
        tool_args = self._parse_json(first_call.get("function", {}).get("arguments", "{}"))

        if tool_name.startswith("sub_agent_"):
            return ModelDecision.sub_agent_call(
                SubAgentCall(
                    agent=tool_name.replace("sub_agent_", ""),
                    task=tool_args.get("task", tool_args.get("text", "")),
                    context_refs=tool_args.get("context_refs", []),
                ),
                reasoning=content or None,
            )

        decision = ModelDecision.tool_call(
            ToolCall(
                id=first_call.get("id", ""),
                name=tool_name,
                arguments=tool_args,
            ),
            reasoning=content or None,
        )
        decision.payload["tool_calls"] = tool_calls
        return decision

    def _parse_json(self, json_str: str) -> dict[str, Any]:
        try:
            result = json.loads(json_str)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            self.logger.warning("invalid_json", json_str=json_str)
            return {}

    def _build_request_kwargs(
        self,
        chat_messages: list[dict[str, Any]],
        all_tools: list[dict[str, Any]],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
        }
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        if all_tools:
            kwargs["tools"] = all_tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = True
        return kwargs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
        session_id: str | None = None,
        reasoning_effort: str = "minimal",
    ) -> ModelResponse:
        """Generate a response from vLLM via Chat Completions."""
        # session_id and reasoning_effort are not used for vLLM.
        _ = session_id
        _ = reasoning_effort

        self.logger.info("llm_call", model=self.model, provider="vllm", base_url=self.base_url)

        chat_messages = self._convert_messages(messages)
        if system:
            chat_messages.insert(0, {"role": "system", "content": system})

        all_tools = (self._convert_tools(tools) if tools else []) + self._convert_agents_to_tools(agents)
        kwargs = self._build_request_kwargs(chat_messages, all_tools, stream=False)

        response = await self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        content = choice.message.content or ""
        finish_reason = choice.finish_reason
        raw_tool_calls = getattr(choice.message, "tool_calls", None)
        tool_calls = self._extract_tool_calls_from_message(raw_tool_calls)
        usage = self._build_usage(response.usage)

        api_logger.log_response(
            model=self.model,
            input_items=chat_messages,
            tools=all_tools or None,
            response_data={
                "status": finish_reason,
                "output_text": content,
                "output": tool_calls,
                "usage_raw": {},
            },
            usage=usage,
        )

        decision = self._build_decision(content=content, tool_calls=tool_calls)
        return ModelResponse(decision=decision, usage=usage, finish_reason=finish_reason)

    async def generate_stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
        session_id: str | None = None,
        reasoning_effort: str = "minimal",
    ) -> AsyncIterator[tuple[str, ModelResponse | None]]:
        """Stream a response from vLLM via Chat Completions SSE.

        Yields (content_delta, None) for each text chunk and ("", response) at the end.
        """
        _ = session_id
        _ = reasoning_effort

        self.logger.info("llm_call_stream", model=self.model, provider="vllm", base_url=self.base_url)

        chat_messages = self._convert_messages(messages)
        if system:
            chat_messages.insert(0, {"role": "system", "content": system})

        all_tools = (self._convert_tools(tools) if tools else []) + self._convert_agents_to_tools(agents)
        kwargs = self._build_request_kwargs(chat_messages, all_tools, stream=True)

        stream = await self.client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        # Chat Completions streaming accumulates tool calls by index.
        # Each delta chunk has tool_calls with index, id (first chunk only), and argument fragments.
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        finish_reason: str | None = None

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None

            # Usage arrives in the final chunk when stream_options.include_usage=True.
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = self._build_usage(chunk_usage)

            if choice is None:
                continue

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta

            # Text delta
            delta_content = getattr(delta, "content", None)
            if delta_content:
                content_parts.append(delta_content)
                yield delta_content, None

            # Tool call deltas (accumulated by index)
            delta_tool_calls = getattr(delta, "tool_calls", None)
            for tc_delta in delta_tool_calls or []:
                idx = tc_delta.index
                if idx not in tool_calls_by_index:
                    tool_calls_by_index[idx] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                current = tool_calls_by_index[idx]
                if tc_delta.id:
                    current["id"] = tc_delta.id
                fn_delta = getattr(tc_delta, "function", None)
                if fn_delta:
                    if getattr(fn_delta, "name", None):
                        current["function"]["name"] = fn_delta.name
                    if getattr(fn_delta, "arguments", None):
                        current["function"]["arguments"] += fn_delta.arguments

        full_content = "".join(content_parts)
        tool_calls = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]
        decision = self._build_decision(content=full_content, tool_calls=tool_calls)

        api_logger.log_response(
            model=self.model,
            input_items=chat_messages,
            tools=all_tools or None,
            response_data={
                "status": finish_reason,
                "output_text": full_content,
                "output": tool_calls,
                "usage_raw": {},
            },
            usage=usage,
        )

        yield "", ModelResponse(decision=decision, usage=usage, finish_reason=finish_reason)
