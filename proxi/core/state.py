"""Agent state management for tracking turns, history, and context."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, TYPE_CHECKING

from pydantic import BaseModel, Field
import json

if TYPE_CHECKING:
    from proxi.interaction.models import FormRequest, FormResponse


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


class WorkspaceConfig(BaseModel):
    """Configuration for the current workspace context.

    This is attached to the AgentState so that prompt builders and tools
    can locate global, agent, and session files on disk without needing
    to re-discover the workspace layout.
    """

    workspace_root: Annotated[str, Field(description="Root of the Proxi workspace (e.g. ~/.proxi)")]
    agent_id: Annotated[str, Field(description="Current agent identifier")]
    session_id: Annotated[str, Field(description="Current session identifier")]

    global_system_prompt_path: Annotated[str, Field(description="Path to global/system_prompt.md")]
    soul_path: Annotated[str, Field(description="Path to agents/<agent_id>/Soul.md")]

    history_path: Annotated[str, Field(description="Path to sessions/<session_id>/history.jsonl")]
    plan_path: Annotated[str, Field(description="Path to sessions/<session_id>/plan.md (optional)")]
    todos_path: Annotated[str, Field(description="Path to sessions/<session_id>/todos.md (optional)")]


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

    # Workspace context (optional)
    workspace: Annotated[WorkspaceConfig | None, Field(default=None, description="Current workspace context, if any")]

    # Form interaction history
    interaction_history: Annotated[list[dict[str, Any]], Field(default_factory=list, description="Records of form interactions")]

    def add_message(self, message: Message) -> None:
        """Add a message to the history and append to history.jsonl if configured."""
        self.history.append(message)

        # Persist only user/assistant messages into history.jsonl so that
        # chat history can be reconstructed later without tool/system noise.
        if (
            self.workspace is not None
            and message.role in ("user", "assistant")
            and self.workspace.history_path
        ):
            self._append_history_jsonl(message)

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

    # --- Internal helpers -------------------------------------------------

    def add_interaction_record(self, req: "FormRequest", res: "FormResponse") -> None:
        """Add an interaction record and persist to history.jsonl if configured."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "goal": req.goal,
            "questions": [q.id for q in req.questions],
            "answers": res.answers,
            "skipped": res.skipped,
        }
        self.interaction_history.append(record)

        if self.workspace is not None and self.workspace.history_path:
            self._append_to_history_file({
                "type": "interaction",
                "goal": req.goal,
                "questions": [q.id for q in req.questions],
                "answers": res.answers,
                "skipped": res.skipped,
            })

    def _append_history_jsonl(self, message: Message) -> None:
        """Append a single message to the workspace history.jsonl file."""
        try:
            path = Path(self.workspace.history_path)  # type: ignore[union-attr]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(message.model_dump_json() + "\n")
        except Exception:
            # History persistence is best-effort; failures should not break the loop.
            return

    def _append_to_history_file(self, obj: dict[str, Any]) -> None:
        """Append a JSON object to the workspace history.jsonl file."""
        try:
            path = Path(self.workspace.history_path)  # type: ignore[union-attr]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obj) + "\n")
        except Exception:
            # History persistence is best-effort; failures should not break the loop.
            return
