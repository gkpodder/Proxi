"""Reflection and verification logic."""

from typing import TYPE_CHECKING

from proxi.core.state import AgentState, TurnState, TurnStatus
from proxi.observability.logging import get_logger

if TYPE_CHECKING:
    from proxi.interaction.models import FormRequest, FormResponse

logger = get_logger(__name__)


class Reflector:
    """Reflector for verifying outputs and deciding on retries."""

    def __init__(self, enabled: bool = True):
        """Initialize the reflector."""
        self.enabled = enabled
        self.logger = logger

    async def reflect(self, state: AgentState, turn: TurnState) -> str | None:
        """
        Reflect on the current turn and generate insights.

        Args:
            state: Current agent state
            turn: Current turn state

        Returns:
            Reflection text or None if reflection is disabled
        """
        if not self.enabled:
            return None

        self.logger.debug("reflection_start", turn=turn.turn_number)

        # Simple reflection logic - can be enhanced with LLM-based reflection
        reflection_parts = []

        if turn.error:
            reflection_parts.append(f"Error occurred: {turn.error}")
            reflection_parts.append("Consider retrying with different approach")

        if turn.action_result:
            if turn.status == TurnStatus.COMPLETED:
                reflection_parts.append("Action completed successfully")

        reflection = "\n".join(reflection_parts) if reflection_parts else None

        if reflection:
            self.logger.debug("reflection_generated", turn=turn.turn_number)

        return reflection

    async def reflect_on_interaction(
        self,
        form_request: "FormRequest",
        form_response: "FormResponse",
        subsequent_reasoning: str,
    ) -> str | None:
        """
        Evaluate whether the form answers resolved the stated goal.
        Returns reflection text or None. Can be extended with LLM-based evaluation.
        """
        if not self.enabled:
            return None
        # Stub: full LLM-based evaluation per spec can be added later
        if form_response.skipped:
            return "User cancelled the form; agent should adapt accordingly."
        return None

    def should_retry(self, state: AgentState, turn: TurnState) -> bool:
        """
        Determine if a turn should be retried.

        Args:
            state: Current agent state
            turn: Current turn state

        Returns:
            True if should retry
        """
        if turn.status != TurnStatus.ERROR:
            return False

        # Don't retry if we've exceeded max turns
        if state.current_turn >= state.max_turns:
            return False

        # Simple retry logic - can be enhanced
        return True
