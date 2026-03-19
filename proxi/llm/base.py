"""Base LLM client interface."""

from collections.abc import Sequence
from typing import Protocol

from proxi.core.state import Message
from proxi.llm.schemas import ModelResponse, SubAgentSpec, ToolSpec


class LLMClient(Protocol):
    """Protocol for LLM clients."""

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents: Sequence[SubAgentSpec] | None = None,
        system: str | None = None,
        session_id: str | None = None,
    ) -> ModelResponse:
        """
        Generate a response from the model.

        Args:
            messages: Conversation history (already assembled by PromptBuilder)
            tools: Available tools
            agents: Available sub-agents
            system: Optional system prompt string (for providers with a top-level system field)
            session_id: Optional session identifier for provider-specific caching optimizations

        Returns:
            Model response with decision and usage
        """
        ...
