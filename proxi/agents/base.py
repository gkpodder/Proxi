"""Base sub-agent interface."""

from typing import Annotated, Any, Protocol

from pydantic import BaseModel, Field


class SubAgentResult(BaseModel):
    """Result from sub-agent execution."""

    summary: Annotated[str, Field(description="Summary of what the sub-agent did")]
    artifacts: Annotated[dict[str, Any], Field(default_factory=dict, description="Artifacts produced (code, files, diffs, answers)")]
    confidence: Annotated[float, Field(ge=0.0, le=1.0, description="Confidence score (0.0 to 1.0)")]
    success: Annotated[bool, Field(description="Whether the sub-agent succeeded")]
    error: Annotated[str | None, Field(default=None, description="Error message if failed")]
    follow_up_suggestions: Annotated[list[str], Field(default_factory=list, description="Optional follow-up suggestions")]


class AgentContext(BaseModel):
    """Context provided to sub-agents."""

    task: Annotated[str, Field(description="Task description")]
    context_refs: Annotated[dict[str, Any], Field(default_factory=dict, description="Context references")]
    history_snapshot: Annotated[list[dict[str, Any]], Field(default_factory=list, description="Relevant history snapshot")]


class SubAgent(Protocol):
    """Protocol for sub-agents."""

    name: str
    description: str
    input_schema: dict[str, Any]

    async def run(
        self,
        context: AgentContext,
        max_turns: int = 10,
        max_tokens: int = 2000,
        max_time: float = 30.0,
    ) -> SubAgentResult:
        """
        Run the sub-agent with given context and budgets.

        Args:
            context: Agent context with task and references
            max_turns: Maximum number of turns for this sub-agent
            max_tokens: Maximum tokens to use
            max_time: Maximum wall-clock time in seconds

        Returns:
            Sub-agent result
        """
        ...


class BaseSubAgent:
    """Base implementation for sub-agents."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        system_prompt: str,
    ):
        """Initialize the sub-agent."""
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.system_prompt = system_prompt

    def to_spec(self) -> dict[str, Any]:
        """Convert to sub-agent specification."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
