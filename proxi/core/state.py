"""Agent state management for tracking turns, history, and context."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class TurnStatus(str, Enum):
    """Status of a single turn in the agent loop."""

    PENDING = "pending"
    REASONING = "reasoning"
    DECIDING = "deciding"
    ACTING = "acting"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    COMPLETED = "completed"
    ERROR = "error"


class AgentStatus(str, Enum):
    """Overall status of the agent."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TurnState:
    """State for a single turn in the agent loop."""

    turn_number: int
    status: TurnStatus = TurnStatus.PENDING
    decision: dict[str, Any] | None = None
    action_result: dict[str, Any] | None = None
    observation: str | None = None
    reflection: str | None = None
    error: str | None = None
    tokens_used: int = 0
    start_time: float | None = None
    end_time: float | None = None


class Message(BaseModel):
    """A message in the conversation history."""

    role: Annotated[str, Field(description="Message role: system, user, assistant, tool, agent")]
    content: Annotated[str | None, Field(default=None, description="Message content (None when tool_calls is present)")]
    name: Annotated[str | None, Field(default=None, description="Name of the tool/agent")]
    tool_call_id: Annotated[str | None, Field(default=None, description="ID of the tool call")]
    tool_calls: Annotated[list[dict[str, Any]] | None, Field(default=None, description="Tool calls for assistant messages")]


class AgentState(BaseModel):
    """Overall state of the agent."""

    status: Annotated[AgentStatus, Field(default=AgentStatus.IDLE)]
    current_turn: Annotated[int, Field(default=0, ge=0)]
    max_turns: Annotated[int, Field(default=50, ge=1)]
    history: Annotated[list[Message], Field(default_factory=list)]
    turns: Annotated[list[TurnState], Field(default_factory=list)]
    context_refs: Annotated[dict[str, Any], Field(default_factory=dict)]
    total_tokens: Annotated[int, Field(default=0, ge=0)]
    start_time: Annotated[float | None, Field(default=None)]
    end_time: Annotated[float | None, Field(default=None)]

    def add_message(self, message: Message) -> None:
        """Add a message to the history."""
        self.history.append(message)

    def add_turn(self, turn: TurnState) -> None:
        """Add a turn state."""
        self.turns.append(turn)

    def get_current_turn(self) -> TurnState | None:
        """Get the current turn state."""
        if self.turns and self.current_turn > 0:
            return self.turns[self.current_turn - 1]
        return None

    def is_done(self) -> bool:
        """Check if the agent is done."""
        return self.status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED)

    def can_continue(self) -> bool:
        """Check if the agent can continue."""
        return (
            not self.is_done()
            and self.current_turn < self.max_turns
            and self.status == AgentStatus.RUNNING
        )
