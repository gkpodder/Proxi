"""OpenAI LLM client implementation using the Responses API."""

import json
import hashlib
from collections.abc import AsyncIterator, Sequence
from typing import Any

from openai import AsyncOpenAI

from proxi.core.state import Message
from proxi.llm.schemas import ModelDecision, ModelResponse, SubAgentCall, SubAgentSpec, ToolCall, ToolSpec
from proxi.observability.api_logger import OpenAIAPILogger
from proxi.observability.logging import get_logger

logger = get_logger(__name__)
api_logger = OpenAIAPILogger()


class OpenAIClient:
    """OpenAI client implementation."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-5-mini-2025-08-07"):
        """Initialize OpenAI client."""
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.logger = logger

    def _to_dict(self, value: Any) -> dict[str, Any]:
        """Best-effort conversion from SDK models to dict."""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return {}

    def _get_field(self, value: Any, key: str) -> Any:
        """Read a field from dicts or objects."""
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)

    def _extract_cached_tokens(self, usage_obj: Any, usage_dict: dict[str, Any]) -> int | None:
        """Extract cached token count across Responses/Chat usage shapes."""
        detail_candidates = [
            usage_dict.get("prompt_tokens_details"),
            usage_dict.get("input_tokens_details"),
            self._get_field(usage_obj, "prompt_tokens_details"),
            self._get_field(usage_obj, "input_tokens_details"),
        ]
        for detail in detail_candidates:
            cached = self._get_field(detail, "cached_tokens")
            if cached is not None:
                try:
                    return int(cached)
                except (TypeError, ValueError):
                    return None
        return None

    def _build_usage(self, usage_obj: Any) -> dict[str, Any]:
        """Build normalized usage dict, preserving cached token details."""
        usage_dict = self._to_dict(usage_obj)
        if not usage_dict and usage_obj is not None:
            # Fallback for SDK objects without model_dump
            usage_dict = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
                "input_tokens": getattr(usage_obj, "input_tokens", None),
                "output_tokens": getattr(usage_obj, "output_tokens", None),
            }

        prompt_tokens = usage_dict.get("prompt_tokens")
        if prompt_tokens is None:
            prompt_tokens = usage_dict.get("input_tokens", 0)
        completion_tokens = usage_dict.get("completion_tokens")
        if completion_tokens is None:
            completion_tokens = usage_dict.get("output_tokens", 0)
        total_tokens = usage_dict.get("total_tokens")
        if total_tokens is None:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        result: dict[str, Any] = {
            "prompt_tokens": prompt_tokens or 0,
            "completion_tokens": completion_tokens or 0,
            "total_tokens": total_tokens or 0,
        }
        cached_tokens = self._extract_cached_tokens(usage_obj, usage_dict)
        if cached_tokens is not None:
            result["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
            result["cache_hit"] = cached_tokens > 0
        return result

    def _message_text(self, msg: Message) -> str:
        """Get message text content with a safe default."""
        return msg.content if msg.content is not None else ""

    def _convert_messages(self, messages: Sequence[Message]) -> list[dict[str, Any]]:
        """Convert internal messages to Responses API input items."""
        input_items: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": msg.tool_call_id or "",
                        "output": self._message_text(msg),
                    }
                )
                continue

            if msg.tool_calls:
                # Preserve assistant function calls for the next turn.
                for tc in msg.tool_calls:
                    function = tc.get("function", {}) if isinstance(
                        tc, dict) else {}
                    arguments = function.get("arguments", "{}")
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments)
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id", ""),
                            "name": function.get("name", ""),
                            "arguments": arguments,
                        }
                    )
                if msg.content:
                    input_items.append(
                        {"role": "assistant", "content": msg.content})
                continue

            role = msg.role if msg.role in {
                "user", "assistant", "system", "developer"} else "user"
            input_items.append(
                {"role": role, "content": self._message_text(msg)})
        return input_items

    def _convert_tools(self, tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        """Convert tool specs to Responses API function tool format."""
        sorted_tools = sorted(tools, key=lambda t: t.name)
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": self._canonicalize_json(tool.parameters),
                # MCP/tool schemas may not satisfy strict mode yet.
                "strict": False,
            }
            for tool in sorted_tools
        ]

    def _convert_agents_to_tools(self, agents: Sequence[SubAgentSpec] | None) -> list[dict[str, Any]]:
        """Represent sub-agents as callable function tools."""
        if not agents:
            return []
        sorted_agents = sorted(agents, key=lambda a: a.name)
        return [
            {
                "type": "function",
                "name": f"sub_agent_{agent.name}",
                "description": f"[Sub-Agent] {agent.description}",
                "parameters": self._canonicalize_json(agent.input_schema),
                "strict": False,
            }
            for agent in sorted_agents
        ]

    def _canonicalize_json(self, value: Any) -> Any:
        """Recursively sort mapping keys for stable request serialization."""
        if isinstance(value, dict):
            return {k: self._canonicalize_json(value[k]) for k in sorted(value.keys())}
        if isinstance(value, list):
            return [self._canonicalize_json(v) for v in value]
        return value

    def _build_prompt_cache_key(
        self,
        input_items: Sequence[dict[str, Any]],
        response_tools: Sequence[dict[str, Any]],
        system: str | None,
        session_id: str | None = None,
    ) -> str:
        """
        Build a deterministic cache key from session identity.

        Using session identity keeps the key stable across turns in the same
        conversation and improves cache consistency for shared prefixes.
        """
        if session_id:
            key_material = {"session_id": session_id}
        else:
            # Fallback for call paths without workspace/session context.
            prefix_items = list(input_items[:8])
            key_material = {
                "model": self.model,
                "instructions": system or "",
                "tools": self._canonicalize_json(list(response_tools)),
                "prefix_items": self._canonicalize_json(prefix_items),
            }
        payload = json.dumps(key_material, sort_keys=True,
                             separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]
        return f"proxi:{digest}"

    def _extract_output_items(self, response: Any) -> list[dict[str, Any]]:
        """Extract output items from a Responses API response."""
        raw_items = getattr(response, "output", None)
        if raw_items is None and isinstance(response, dict):
            raw_items = response.get("output")
        if not raw_items:
            return []

        items: list[dict[str, Any]] = []
        for item in raw_items:
            if isinstance(item, dict):
                items.append(item)
            else:
                items.append(self._to_dict(item))
        return items

    def _extract_text(self, response: Any, output_items: Sequence[dict[str, Any]]) -> str:
        """Extract assistant text output from Responses API output."""
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text
        if isinstance(response, dict) and isinstance(response.get("output_text"), str):
            return response["output_text"]

        parts: list[str] = []
        for item in output_items:
            item_type = item.get("type")
            if item_type == "message":
                for content in item.get("content", []):
                    if not isinstance(content, dict):
                        continue
                    if content.get("type") in {"output_text", "text", "input_text"}:
                        text = content.get("text")
                        if isinstance(text, str):
                            parts.append(text)
            elif item_type in {"output_text", "text"}:
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    def _extract_function_calls(self, output_items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract function calls and map them to the existing internal shape."""
        tool_calls: list[dict[str, Any]] = []
        for idx, item in enumerate(output_items):
            item_type = item.get("type")
            if item_type not in {"function_call", "tool_call"}:
                continue
            call_id = item.get("call_id") or item.get("id") or f"call_{idx}"
            name = item.get("name") or ""
            arguments = item.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)
            tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": arguments,
                    },
                }
            )
        return tool_calls

    def _build_decision(self, content: str, tool_calls: list[dict[str, Any]]) -> ModelDecision:
        """Build a provider-agnostic decision object from parsed output."""
        if not tool_calls:
            return ModelDecision.respond(content=content, reasoning=None)

        first_call = tool_calls[0]
        tool_name = first_call.get("function", {}).get("name", "")
        tool_args = self._parse_json(first_call.get(
            "function", {}).get("arguments", "{}"))

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

    def _supports_reasoning_controls(self) -> bool:
        """Return True when the selected model supports reasoning controls."""
        normalized_model = self.model.strip().lower()
        reasoning_model_prefixes = (
            "gpt-5",
            "o1",
            "o3",
            "o4",
        )
        return normalized_model.startswith(reasoning_model_prefixes)

    def _responses_api_reasoning_effort(self, effort: str) -> str:
        """Map user-facing effort labels to values accepted by the Responses API per model."""
        e = (effort or "minimal").strip().lower()
        normalized = self.model.strip().lower()
        # GPT-5 and o-series models do not accept the legacy "minimal" label.
        if normalized.startswith(("gpt-5", "o1", "o3", "o4")) and e == "minimal":
            return "low"
        return e

    def _build_response_create_kwargs(
        self,
        input_items: list[dict[str, Any]],
        response_tools: list[dict[str, Any]],
        system: str | None,
        *,
        stream: bool,
        session_id: str | None,
        reasoning_effort: str = "minimal",
    ) -> tuple[dict[str, Any], str]:
        """Build shared kwargs for Responses API create calls."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
        }
        if stream:
            kwargs["stream"] = True
        if self._supports_reasoning_controls():
            kwargs["reasoning"] = {
                "effort": self._responses_api_reasoning_effort(reasoning_effort),
            }
        if system:
            kwargs["instructions"] = system
        if response_tools:
            kwargs["tools"] = response_tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = True
        prompt_cache_key = self._build_prompt_cache_key(
            input_items, response_tools, system, session_id=session_id)
        kwargs["prompt_cache_key"] = prompt_cache_key
        return kwargs, prompt_cache_key

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
        session_id: str | None = None,
        reasoning_effort: str = "minimal",
    ) -> ModelResponse:
        """Generate a response from OpenAI Responses API."""
        self.logger.info("llm_call", model=self.model, provider="openai", reasoning_effort=reasoning_effort)
        input_items = self._convert_messages(messages)
        response_tools = (self._convert_tools(tools) if tools else [
        ]) + self._convert_agents_to_tools(agents)

        kwargs, prompt_cache_key = self._build_response_create_kwargs(
            input_items=input_items,
            response_tools=response_tools,
            system=system,
            stream=False,
            session_id=session_id,
            reasoning_effort=reasoning_effort,
        )

        response = await self.client.responses.create(**kwargs)
        usage = self._build_usage(getattr(response, "usage", None))
        output_items = self._extract_output_items(response)
        content = self._extract_text(response, output_items)
        tool_calls = self._extract_function_calls(output_items)
        finish_reason = getattr(response, "status", None)

        api_logger.log_response(
            model=self.model,
            input_items=input_items,
            tools=response_tools or None,
            response_data={
                "status": finish_reason,
                "output_text": content,
                "output": output_items,
                "usage_raw": self._to_dict(getattr(response, "usage", None)),
                "prompt_cache_key": prompt_cache_key,
            },
            usage=usage,
        )

        decision = self._build_decision(content=content, tool_calls=tool_calls)
        return ModelResponse(
            decision=decision,
            usage=usage,
            finish_reason=finish_reason,
        )

    async def generate_stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
        session_id: str | None = None,
        reasoning_effort: str = "minimal",
    ) -> AsyncIterator[tuple[str, ModelResponse | None]]:
        """
        Generate a response with streaming. Yields (content_delta, None) for each
        text chunk and ("", response) at the end.
        """
        self.logger.info("llm_call_stream", model=self.model, provider="openai", reasoning_effort=reasoning_effort)
        input_items = self._convert_messages(messages)
        response_tools = (self._convert_tools(tools) if tools else [
        ]) + self._convert_agents_to_tools(agents)

        kwargs, prompt_cache_key = self._build_response_create_kwargs(
            input_items=input_items,
            response_tools=response_tools,
            system=system,
            stream=True,
            session_id=session_id,
            reasoning_effort=reasoning_effort,
        )

        stream = await self.client.responses.create(**kwargs)
        content_parts: list[str] = []
        # Preserve ordering from first appearance.
        tool_calls_by_id: dict[str, dict[str, Any]] = {}
        usage: dict[str, Any] = {"prompt_tokens": 0,
                                 "completion_tokens": 0, "total_tokens": 0}
        finish_reason: str | None = None
        final_response: Any | None = None

        async for event in stream:
            event_type = getattr(event, "type", None)

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    content_parts.append(delta)
                    yield delta, None
                continue

            if event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                item_dict = self._to_dict(item)
                if item_dict.get("type") in {"function_call", "tool_call"}:
                    call_id = item_dict.get("call_id") or item_dict.get("id")
                    if call_id:
                        arguments = item_dict.get("arguments", "{}")
                        if not isinstance(arguments, str):
                            arguments = json.dumps(arguments)
                        tool_calls_by_id[call_id] = {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": item_dict.get("name", ""),
                                "arguments": arguments,
                            },
                        }
                continue

            if event_type == "response.function_call_arguments.delta":
                call_id = getattr(event, "call_id", None)
                delta = getattr(event, "delta", "")
                if call_id and delta:
                    current = tool_calls_by_id.setdefault(
                        call_id,
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    current["function"]["arguments"] = (
                        current["function"]["arguments"] or "") + delta
                continue

            if event_type == "response.function_call_arguments.done":
                call_id = getattr(event, "call_id", None)
                full_args = getattr(event, "arguments", None)
                if call_id and isinstance(full_args, str):
                    current = tool_calls_by_id.setdefault(
                        call_id,
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    current["function"]["arguments"] = full_args
                continue

            if event_type == "response.completed":
                final_response = getattr(event, "response", None)
                if final_response is not None:
                    usage = self._build_usage(
                        getattr(final_response, "usage", None))
                    finish_reason = getattr(final_response, "status", None)
                continue

        # Best-effort fallback if stream doesn't emit response.completed.
        if final_response is None:
            get_final_response = getattr(stream, "get_final_response", None)
            if callable(get_final_response):
                try:
                    final_response = await get_final_response()
                except Exception:
                    final_response = None

        full_content = "".join(content_parts)
        if final_response is not None:
            usage = self._build_usage(getattr(final_response, "usage", None))
            finish_reason = getattr(final_response, "status", None)
            output_items = self._extract_output_items(final_response)
            parsed_text = self._extract_text(final_response, output_items)
            if parsed_text:
                full_content = parsed_text
            parsed_tool_calls = self._extract_function_calls(output_items)
            if parsed_tool_calls:
                tool_calls_by_id = {tc["id"]: tc for tc in parsed_tool_calls}

        tool_calls = list(tool_calls_by_id.values())
        decision = self._build_decision(
            content=full_content, tool_calls=tool_calls)

        api_logger.log_response(
            model=self.model,
            input_items=input_items,
            tools=response_tools or None,
            response_data={
                "status": finish_reason,
                "output_text": full_content,
                "output": tool_calls,
                "usage_raw": self._to_dict(getattr(final_response, "usage", None)) if final_response is not None else {},
                "prompt_cache_key": prompt_cache_key,
            },
            usage=usage,
        )

        yield "", ModelResponse(decision=decision, usage=usage, finish_reason=finish_reason)

    def _parse_json(self, json_str: str) -> dict[str, Any]:
        """Parse JSON string safely."""
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            self.logger.warning("invalid_json", json_str=json_str)
            return {}
