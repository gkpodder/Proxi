"""Anthropic Claude LLM client implementation."""

from collections.abc import AsyncIterator, Sequence
from typing import Any

from anthropic import AsyncAnthropic

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


class AnthropicClient:
    """Anthropic Claude client implementation."""

    def __init__(self, api_key: str | None = None, model: str = "claude-3-5-sonnet-20241022"):
        """Initialize Anthropic client."""
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.logger = logger

    def _convert_messages(self, messages: Sequence[Message]) -> list[dict[str, Any]]:
        """Convert internal messages to Anthropic format."""
        result = []
        for msg in messages:
            # Anthropic uses "user" and "assistant" roles
            # Map "tool" to "user" with appropriate content
            role = msg.role
            if role == "tool":
                role = "user"  # Anthropic doesn't have a tool role

            anthropic_msg: dict[str, Any] = {
                "role": role,
                "content": msg.content,
            }
            result.append(anthropic_msg)
        return result

    def _convert_tools(self, tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        """Convert tool specs to Anthropic format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
        session_id: str | None = None,
        reasoning_effort: str = "minimal",
    ) -> ModelResponse:
        """Generate a response from Anthropic."""
        # session_id and reasoning_effort are intentionally unused for Anthropic.
        # Standard Claude models don't have a reasoning effort knob equivalent to OpenAI's.
        _ = session_id
        _ = reasoning_effort
        self.logger.info("llm_call", model=self.model, provider="anthropic")
        anthropic_messages = self._convert_messages(messages)
        anthropic_tools = self._convert_tools(tools) if tools else None

        # Note: Sub-agents are not directly supported by Anthropic API
        # They would need to be represented as tools or handled differently
        if agents:
            self.logger.warning("sub_agents_not_supported", count=len(agents))

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": 4096,
        }

        if system:
            # Use the structured system format so Anthropic can place a KV
            # cache breakpoint at the end of the stable prefix.  This ensures
            # the system prompt + tools array are cached on every turn.
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = await self.client.messages.create(**kwargs)

        # Determine decision type
        content = response.content[0] if response.content else None

        if content and content.type == "tool_use":
            # Tool call decision
            decision = ModelDecision.tool_call(
                ToolCall(
                    id=content.id,
                    name=content.name,
                    arguments=content.input,
                ),
                reasoning=None,
            )
        elif content and content.type == "text":
            # Respond decision
            decision = ModelDecision.respond(
                content=content.text,
                reasoning=None,
            )
        else:
            # Fallback
            decision = ModelDecision.respond(
                content="",
                reasoning=None,
            )

        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        return ModelResponse(
            decision=decision,
            usage=usage,
            finish_reason=response.stop_reason,
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
        Generate a response; yields content in one chunk then the full response.
        (Anthropic streaming can be added later for token-by-token.)
        """
        response = await self.generate(
            messages,
            tools=tools,
            agents=agents,
            system=system,
            session_id=session_id,
            reasoning_effort=reasoning_effort,
        )
        content = response.decision.payload.get("content") or ""
        if content:
            yield content, None
        yield "", response
