"""OpenAI LLM client implementation."""

from collections.abc import AsyncIterator, Sequence
from typing import Any

from openai import AsyncOpenAI

from proxi.core.state import Message
from proxi.llm.schemas import ModelDecision, ModelResponse, SubAgentSpec, ToolCall, ToolSpec
from proxi.observability.logging import get_logger
from proxi.observability.api_logger import OpenAIAPILogger

logger = get_logger(__name__)
api_logger = OpenAIAPILogger()


class OpenAIClient:
    """OpenAI client implementation."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o"):
        """Initialize OpenAI client."""
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.logger = logger

    def _convert_messages(self, messages: Sequence[Message]) -> list[dict[str, Any]]:
        """Convert internal messages to OpenAI format."""
        result = []
        for msg in messages:
            openai_msg: dict[str, Any] = {
                "role": msg.role,
            }
            # OpenAI requires content to be None when tool_calls is present
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
                openai_msg["content"] = None
            else:
                openai_msg["content"] = msg.content or None
            if msg.name:
                openai_msg["name"] = msg.name
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            result.append(openai_msg)
        return result

    def _convert_tools(self, tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        """Convert tool specs to OpenAI format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
    ) -> ModelResponse:
        """Generate a response from OpenAI."""
        self.logger.info("llm_call", model=self.model, provider="openai")
        openai_messages = self._convert_messages(messages)
        # Prepend a system message when provided. PromptBuilder ensures that
        # `messages` themselves do not contain a separate system message.
        if system:
            openai_messages = [{"role": "system", "content": system}] + openai_messages
        openai_tools = self._convert_tools(tools) if tools else None

        # Convert sub-agents to tools since OpenAI doesn't natively support sub-agents
        # We represent them as special tools that the agent can call
        agent_tools = []
        if agents:
            for agent in agents:
                agent_tools.append({
                    "type": "function",
                    "function": {
                        "name": f"sub_agent_{agent.name}",
                        "description": f"[Sub-Agent] {agent.description}",
                        "parameters": agent.input_schema,
                    },
                })
        
        # Combine regular tools and agent tools
        if agent_tools:
            if openai_tools:
                openai_tools = openai_tools + agent_tools
            else:
                openai_tools = agent_tools

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
        }

        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        message = choice.message

        # Log API call
        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }
        
        response_data = {
            "choices": [
                {
                    "message": {
                        "role": message.role,
                        "content": message.content,
                    },
                    "finish_reason": choice.finish_reason,
                }
            ],
            "finish_reason": choice.finish_reason,
        }
        
        api_logger.log_chat_completion(
            model=self.model,
            messages=openai_messages,
            tools=openai_tools,
            response_data=response_data,
            usage=usage,
        )

        # Determine decision type
        if message.tool_calls:
            # Tool call decision
            tool_call = message.tool_calls[0]
            tool_name = tool_call.function.name
            
            # Convert tool_calls to dict format for storage
            tool_calls_dict = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
            
            # Check if this is a sub-agent call (prefixed with "sub_agent_")
            if tool_name.startswith("sub_agent_"):
                # Extract agent name and convert to sub-agent call
                agent_name = tool_name.replace("sub_agent_", "")
                arguments = self._parse_json(tool_call.function.arguments)
                
                from proxi.llm.schemas import SubAgentCall
                decision = ModelDecision.sub_agent_call(
                    SubAgentCall(
                        agent=agent_name,
                        task=arguments.get("task", arguments.get("text", "")),
                        context_refs=arguments.get("context_refs", []),
                    ),
                    reasoning=message.content,
                )
            else:
                decision = ModelDecision.tool_call(
                    ToolCall(
                        id=tool_call.id,
                        name=tool_name,
                        arguments=self._parse_json(tool_call.function.arguments),
                    ),
                    reasoning=message.content,
                )
                # Store tool_calls in decision payload for later use
                decision.payload["tool_calls"] = tool_calls_dict
        else:
            # Respond decision
            decision = ModelDecision.respond(
                content=message.content or "",
                reasoning=None,
            )

        return ModelResponse(
            decision=decision,
            usage=usage,
            finish_reason=choice.finish_reason,
        )

    async def generate_stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[tuple[str, ModelResponse | None]]:
        """
        Generate a response with streaming. Yields (content_delta, None) for each
        token and (\"\", response) at the end.
        """
        self.logger.info("llm_call_stream", model=self.model, provider="openai")
        openai_messages = self._convert_messages(messages)
        if system:
            openai_messages = [{"role": "system", "content": system}] + openai_messages
        openai_tools = self._convert_tools(tools) if tools else None
        agent_tools = []
        if agents:
            for agent in agents:
                agent_tools.append({
                    "type": "function",
                    "function": {
                        "name": f"sub_agent_{agent.name}",
                        "description": f"[Sub-Agent] {agent.description}",
                        "parameters": agent.input_schema,
                    },
                })
        if agent_tools:
            openai_tools = (openai_tools or []) + agent_tools

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "stream": True,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        stream = await self.client.chat.completions.create(**kwargs)
        content_parts: list[str] = []
        tool_calls_acc: list[dict[str, Any]] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        finish_reason: str | None = None

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if getattr(delta, "content", None) and delta.content:
                content_parts.append(delta.content)
                yield delta.content, None
            if getattr(delta, "tool_calls", None) and delta.tool_calls:
                for tc in delta.tool_calls:
                    if getattr(tc, "index", None) is not None:
                        while len(tool_calls_acc) <= (tc.index or 0):
                            tool_calls_acc.append({
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                        idx = tc.index or 0
                        if getattr(tc, "id", None):
                            tool_calls_acc[idx]["id"] = tc.id or ""
                        if getattr(tc, "function", None):
                            if getattr(tc.function, "name", None):
                                tool_calls_acc[idx]["function"]["name"] = (tool_calls_acc[idx]["function"]["name"] or "") + (tc.function.name or "")
                            if getattr(tc.function, "arguments", None):
                                tool_calls_acc[idx]["function"]["arguments"] = (tool_calls_acc[idx]["function"]["arguments"] or "") + (tc.function.arguments or "")
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason
            if getattr(chunk, "usage", None) and chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }

        full_content = "".join(content_parts)
        if tool_calls_acc:
            tool_call = tool_calls_acc[0]
            tool_name = tool_call["function"]["name"]
            arguments = self._parse_json(tool_call["function"]["arguments"] or "{}")
            if tool_name.startswith("sub_agent_"):
                from proxi.llm.schemas import SubAgentCall
                decision = ModelDecision.sub_agent_call(
                    SubAgentCall(
                        agent=tool_name.replace("sub_agent_", ""),
                        task=arguments.get("task", arguments.get("text", "")),
                        context_refs=arguments.get("context_refs", []),
                    ),
                    reasoning=full_content or None,
                )
            else:
                decision = ModelDecision.tool_call(
                    ToolCall(id=tool_call["id"], name=tool_name, arguments=arguments),
                    reasoning=full_content or None,
                )
                decision.payload["tool_calls"] = tool_calls_acc
        else:
            decision = ModelDecision.respond(content=full_content, reasoning=None)

        # Log streamed API call
        response_data_stream = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": full_content,
                    },
                    "finish_reason": finish_reason,
                }
            ],
            "finish_reason": finish_reason,
        }
        
        api_logger.log_chat_completion(
            model=self.model,
            messages=openai_messages,
            tools=openai_tools,
            response_data=response_data_stream,
            usage=usage,
        )

        yield "", ModelResponse(decision=decision, usage=usage, finish_reason=finish_reason)

    def _parse_json(self, json_str: str) -> dict[str, Any]:
        """Parse JSON string safely."""
        import json

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            self.logger.warning("invalid_json", json_str=json_str)
            return {}
