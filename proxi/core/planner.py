"""Primary agent planner logic."""

from collections.abc import Awaitable, Callable

from proxi.core.state import AgentState
from proxi.llm.base import LLMClient
from proxi.llm.schemas import ModelDecision, SubAgentSpec, ToolSpec
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class Planner:
    """Primary agent planner for high-level planning and delegation."""

    def __init__(self, llm_client: LLMClient):
        """Initialize the planner."""
        self.llm_client = llm_client
        self.logger = logger

    async def decide(
        self,
        state: AgentState,
        tools: list[ToolSpec],
        agents: list[SubAgentSpec] | None = None,
        stream_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[ModelDecision, dict[str, int]]:
        """
        Make a decision based on current state.

        Args:
            state: Current agent state
            tools: Available tools
            agents: Available sub-agents
            stream_callback: If set and client supports streaming, called with each content token.

        Returns:
            Tuple of (Model decision, token usage)
        """
        self.logger.debug(
            "planner_decide",
            turn=state.current_turn,
            history_length=len(state.history),
        )

        generate_stream = getattr(self.llm_client, "generate_stream", None)
        if stream_callback and generate_stream is not None:
            response = None
            async for chunk, resp in generate_stream(
                messages=state.history,
                tools=tools,
                agents=agents or [],
            ):
                if chunk:
                    await stream_callback(chunk)
                if resp is not None:
                    response = resp
            if response is None:
                response = await self.llm_client.generate(
                    messages=state.history,
                    tools=tools,
                    agents=agents or [],
                )
            return response.decision, response.usage
        else:
            response = await self.llm_client.generate(
                messages=state.history,
                tools=tools,
                agents=agents or [],
            )
            return response.decision, response.usage
