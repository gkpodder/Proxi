"""Agent state management for tracking turns, history, and context."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import atexit
import os
from pathlib import Path
import queue
import threading
from typing import Annotated, Any, TYPE_CHECKING

from pydantic import BaseModel, Field
import json
from proxi.observability.logging import get_logger
from proxi.observability.perf import elapsed_ms, emit_perf, now_ns

logger = get_logger(__name__)

if TYPE_CHECKING:
    from proxi.interaction.models import FormRequest, FormResponse


class _HistoryWriter:
    """Background writer to keep history persistence off the event loop."""

    def __init__(self) -> None:
        self._enabled = os.getenv("PROXI_ASYNC_HISTORY_WRITE", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        self._queue: queue.SimpleQueue[tuple[str, str | threading.Event]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._stop = False
        if self._enabled:
            self._thread = threading.Thread(target=self._run, name="proxi-history-writer", daemon=True)
            self._thread.start()
            atexit.register(self.close)

    def append(self, path: Path, payload: str) -> None:
        if not self._enabled:
            self._write(path, payload)
            return
        self._queue.put((str(path), payload))

    def drain(self, path: Path, timeout: float = 2.0) -> None:
        """Block until all queued writes for *path* have been flushed to disk.

        Used by ``rewrite_history`` to prevent the background thread from
        appending stale messages after the atomic file replace.
        """
        if not self._enabled or self._thread is None:
            return
        event = threading.Event()
        self._queue.put((str(path), event))
        event.wait(timeout=timeout)

    def close(self) -> None:
        self._stop = True
        self._queue.put(("", ""))
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _run(self) -> None:
        while not self._stop:
            path_str, payload = self._queue.get()
            if not path_str and not payload:
                continue
            if isinstance(payload, threading.Event):
                # Barrier item: signal the waiting caller that all prior writes
                # for this path have been processed.
                payload.set()
                continue
            self._write(Path(path_str), payload)

    def _write(self, path: Path, payload: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(payload)
        except Exception:
            return


_history_writer = _HistoryWriter()


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

    # When plan mode is active, manage_plan writes here instead of plan_path.
    # Points to agents/<agent_id>/plans/in-progress.md so the plan lives in plans/ from the start.
    active_plan_path: Annotated[str | None, Field(default=None, description="Override path for manage_plan during plan mode")] = None

    curr_working_dir: Annotated[
        str | None,
        Field(default=None, description="Root directory for file and shell tool operations"),
    ]


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


def _inject_missing_tool_outputs(messages: list[Message]) -> list[Message]:
    """Ensure each assistant tool_call has a following tool message (OpenAI API requirement).

    Older sessions only persisted user/assistant lines; on reload the model saw
    function_call items without outputs. Synthesize placeholder outputs for any
    missing call_ids so the conversation can continue.
    """
    out: list[Message] = []
    i = 0
    n = len(messages)
    while i < n:
        m = messages[i]
        out.append(m)
        if m.role == "assistant" and m.tool_calls:
            needed: list[str] = []
            for tc in m.tool_calls:
                if isinstance(tc, dict):
                    tid = tc.get("id")
                    if isinstance(tid, str) and tid:
                        needed.append(tid)
            have: set[str] = set()
            i += 1
            while i < n and messages[i].role == "tool":
                tm = messages[i]
                out.append(tm)
                if tm.tool_call_id:
                    have.add(tm.tool_call_id)
                i += 1
            for tid in needed:
                if tid not in have:
                    out.append(
                        Message(
                            role="tool",
                            content=(
                                "[Tool result was missing from saved session history; "
                                "retry the tool if you still need it.]"
                            ),
                            tool_call_id=tid,
                            name=None,
                        )
                    )
            continue
        i += 1
    return out


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

    # Plan mode flag — set when the agent is in an interactive planning session.
    # Runtime-only; not persisted in history.jsonl.
    plan_mode: Annotated[bool, Field(default=False, description="True while agent is in plan-writing mode")] = False

    # Reasoning effort override — "minimal" (default), "medium", or "high".
    # Set to "medium" during plan-mode and plan execution; reset to "minimal" otherwise.
    # Runtime-only; not persisted in history.jsonl.
    reasoning_effort: Annotated[str, Field(default="minimal", description="Reasoning effort for LLM calls: minimal, medium, or high")] = "minimal"

    def add_message(self, message: Message) -> None:
        """Add a message to the history and append to history.jsonl if configured."""
        self.history.append(message)

        # Persist user/assistant/tool messages. Tool outputs must be stored next to
        # assistant tool_calls so sessions reloaded from disk (e.g. gateway lanes)
        # satisfy OpenAI Responses API input (every function_call needs output).
        if (
            self.workspace is not None
            and message.role in ("user", "assistant", "tool")
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

    # --- Class-level loaders -----------------------------------------------

    @classmethod
    def load(cls, history_path: Path) -> "AgentState | None":
        """Reconstruct an AgentState from a persisted history.jsonl file.

        Returns None if the file does not exist or is empty.
        User, assistant, and tool messages are stored in history.jsonl so tool
        call/result pairs stay aligned when continuing via
        ``AgentLoop.run_continue()``.
        """
        if not history_path.exists():
            return None
        messages: list[Message] = []
        try:
            with history_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "role" in obj:
                        messages.append(Message(**obj))
        except OSError:
            return None
        if not messages:
            return None
        messages = _inject_missing_tool_outputs(messages)
        return cls(
            status=AgentStatus.IDLE,
            history=messages,
            current_turn=0,
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

    def rewrite_history(self, messages: list[Message]) -> None:
        """Replace in-memory history and atomically rewrite history.jsonl.

        Used after context compaction. Drains the background _history_writer
        queue before the atomic replace so that queued appends from the
        compacted turns do not overwrite the new file after the swap.
        """
        self.history = list(messages)
        if self.workspace is not None and self.workspace.history_path:
            path = Path(self.workspace.history_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".jsonl.tmp")
            try:
                # Flush any queued appends for this path before replacing the
                # file, otherwise the background thread may append stale
                # messages after the atomic swap.
                _history_writer.drain(path)
                payload = "".join(m.model_dump_json() + "\n" for m in messages)
                tmp.write_text(payload, encoding="utf-8")
                tmp.replace(path)  # atomic on POSIX
                logger.debug("history_rewritten path=%s messages=%d", path, len(messages))
            except Exception as exc:
                logger.error("history_rewrite_failed path=%s error=%r", path, exc)

    def _append_history_jsonl(self, message: Message) -> None:
        """Append a single message to the workspace history.jsonl file."""
        start_ns = now_ns()
        try:
            path = Path(self.workspace.history_path)  # type: ignore[union-attr]
            payload = message.model_dump_json() + "\n"
            _history_writer.append(path, payload)
            emit_perf(
                "perf_history_write",
                kind="message",
                bytes=len(payload.encode("utf-8")),
                elapsed_ms=round(elapsed_ms(start_ns), 3),
            )
        except Exception:
            # History persistence is best-effort; failures should not break the loop.
            return

    def _append_to_history_file(self, obj: dict[str, Any]) -> None:
        """Append a JSON object to the workspace history.jsonl file."""
        start_ns = now_ns()
        try:
            path = Path(self.workspace.history_path)  # type: ignore[union-attr]
            payload = json.dumps(obj) + "\n"
            _history_writer.append(path, payload)
            emit_perf(
                "perf_history_write",
                kind="interaction",
                bytes=len(payload.encode("utf-8")),
                elapsed_ms=round(elapsed_ms(start_ns), 3),
            )
        except Exception:
            # History persistence is best-effort; failures should not break the loop.
            return
