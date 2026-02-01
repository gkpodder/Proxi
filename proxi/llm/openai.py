"""OpenAI LLM client implementation."""

from collections.abc import Sequence
from typing import Any

from openai import AsyncOpenAI

from proxi.core.state import Message
from proxi.llm.schemas import (
    DecisionType,
    ModelDecision,
    ModelResponse,
    SubAgentSpec,
    ToolCall,
    ToolSpec,
)
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


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
    ) -> ModelResponse:
        """Generate a response from OpenAI."""
        self.logger.info("llm_call", model=self.model, provider="openai")
        openai_messages = self._convert_messages(messages)
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

        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }

        return ModelResponse(
            decision=decision,
            usage=usage,
            finish_reason=choice.finish_reason,
        )

    def _parse_json(self, json_str: str) -> dict[str, Any]:
        """Parse JSON string safely."""
        import json

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            self.logger.warning("invalid_json", json_str=json_str)
            return {}
