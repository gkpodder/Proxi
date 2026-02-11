"""Sub-agent registry and manager."""

import asyncio
import time
from collections.abc import Sequence
from typing import Any

from proxi.agents.base import AgentContext, BaseSubAgent, SubAgent, SubAgentResult
from proxi.llm.schemas import SubAgentSpec
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class SubAgentRegistry:
    """Registry for managing sub-agents."""

    def __init__(self):
        """Initialize the registry."""
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent) -> None:
        """Register a sub-agent."""
        self._agents[agent.name] = agent
        logger.debug("sub_agent_registered", name=agent.name)

    def get(self, name: str) -> SubAgent | None:
        """Get a sub-agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> Sequence[SubAgent]:
        """List all registered sub-agents."""
        return list(self._agents.values())

    def to_specs(self) -> list[SubAgentSpec]:
        """Convert all sub-agents to specifications."""
        return [
            SubAgentSpec(
                name=agent.name,
                description=agent.description,
                input_schema=agent.input_schema if hasattr(agent, "input_schema") else {},
            )
            for agent in self._agents.values()
        ]


class SubAgentManager:
    """Manager for sub-agent lifecycle and execution."""

    def __init__(self, registry: SubAgentRegistry):
        """Initialize the sub-agent manager."""
        self.registry = registry
        self.logger = logger

    async def run(
        self,
        agent_name: str,
        context: AgentContext,
        max_turns: int = 10,
        max_tokens: int = 2000,
        max_time: float = 30.0,
    ) -> SubAgentResult:
        """
        Run a sub-agent with budgets and lifecycle management.

        Args:
            agent_name: Name of the sub-agent to run
            context: Agent context
            max_turns: Maximum turns for the sub-agent
            max_tokens: Maximum tokens
            max_time: Maximum wall-clock time in seconds

        Returns:
            Sub-agent result
        """
        agent = self.registry.get(agent_name)
        if agent is None:
            return SubAgentResult(
                summary=f"Sub-agent '{agent_name}' not found",
                artifacts={},
                confidence=0.0,
                success=False,
                error=f"Sub-agent '{agent_name}' not found in registry",
            )

        self.logger.info(
            "sub_agent_start",
            agent=agent_name,
            task=context.task[:100] if context.task else "",
        )

        start_time = time.time()

        try:
            # Run with timeout
            result = await asyncio.wait_for(
                agent.run(
                    context=context,
                    max_turns=max_turns,
                    max_tokens=max_tokens,
                    max_time=max_time,
                ),
                timeout=max_time,
            )

            elapsed = time.time() - start_time
            self.logger.info(
                "sub_agent_complete",
                agent=agent_name,
                success=result.success,
                confidence=result.confidence,
                elapsed=elapsed,
            )

            return result

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            self.logger.warning(
                "sub_agent_timeout",
                agent=agent_name,
                elapsed=elapsed,
                max_time=max_time,
            )
            return SubAgentResult(
                summary=f"Sub-agent '{agent_name}' timed out after {elapsed:.2f}s",
                artifacts={},
                confidence=0.0,
                success=False,
                error=f"Sub-agent execution exceeded maximum time of {max_time}s",
            )

        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(
                "sub_agent_error",
                agent=agent_name,
                error=str(e),
                elapsed=elapsed,
            )
            return SubAgentResult(
                summary=f"Sub-agent '{agent_name}' encountered an error",
                artifacts={},
                confidence=0.0,
                success=False,
                error=str(e),
            )
