"""AgentLane — asyncio queue + processing task per session."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from proxi.core.loop import AgentLoop
from proxi.core.state import AgentState, WorkspaceConfig
from proxi.gateway.events import GatewayEvent
from proxi.gateway.lanes.budget import BudgetExceeded, LaneBudget
from proxi.observability.logging import get_logger

logger = get_logger(__name__)

_SUMMARIZER_PROMPT = """\
Summarize the following conversation in ~200 words. Focus on:
- What the user asked for
- What was accomplished (key actions, files changed, decisions made)
- Any errors and how they were resolved
- Useful facts for future reference

Also output a JSON array of 3-5 topic tags on the last line prefixed with TAGS:
Example last line: TAGS: ["docker", "deployment", "debugging"]

Conversation:
{transcript}
"""


_CHEAP_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
}


def _build_summarizer_client(llm_client: Any) -> Any:
    """Return a cheap LLM client for session summarization.

    Priority:
    1. ``PROXI_MEMORY_SUMMARIZER_MODEL`` env var (explicit override).
    2. Cheapest model for the detected provider (anthropic → Haiku, openai → gpt-4o-mini).
    3. Fall back to *llm_client* itself (covers vllm / unknown providers).
    """
    env_model = os.environ.get("PROXI_MEMORY_SUMMARIZER_MODEL", "").strip()
    cls_name = type(llm_client).__name__  # "AnthropicClient" | "OpenAIClient" | other

    if "Anthropic" in cls_name:
        provider = "anthropic"
    elif "OpenAI" in cls_name:
        provider = "openai"
    else:
        # Unknown provider (vllm, custom) — reuse the existing client as-is.
        return llm_client

    target_model = env_model or _CHEAP_MODELS[provider]

    # If the current client is already using the target model, reuse it.
    current_model = getattr(llm_client, "model", None)
    if current_model == target_model:
        return llm_client

    try:
        from proxi.cli.main import create_llm_client
        return create_llm_client(provider=provider, model=target_model)
    except Exception:
        # API key missing or other setup error — fall back to the main client.
        return llm_client


async def _summarize_session(
    agent_id: str,
    session_id: str,
    history: list[Any],
    memory_manager: Any,
    llm_client: Any,
) -> None:
    """Background task: summarize a completed session and store in episodic memory."""
    # Only summarize sessions with meaningful content (at least 3 user turns)
    user_msgs = [m for m in history if getattr(m, "role", None) == "user"]
    if len(user_msgs) < 3:
        return

    # Build a compact transcript (skip large tool results)
    lines: list[str] = []
    for msg in history:
        role = getattr(msg, "role", "")
        content = getattr(msg, "content", None) or ""
        if role in ("user", "assistant") and content:
            lines.append(f"{role.upper()}: {content[:500]}")
        elif role == "tool" and content:
            lines.append(f"TOOL RESULT: {content[:200]}")
    transcript = "\n".join(lines)[:6000]  # keep within cheap model's context

    prompt = _SUMMARIZER_PROMPT.format(transcript=transcript)
    try:
        summarizer_client = _build_summarizer_client(llm_client)
        from proxi.core.state import Message as _Message
        resp = await summarizer_client.generate(
            messages=[_Message(role="user", content=prompt)],
        )
        raw = ""
        if hasattr(resp, "content"):
            raw = resp.content or ""
        elif isinstance(resp, dict):
            raw = resp.get("content", "") or ""
        elif isinstance(resp, str):
            raw = resp

        # Extract tags from last line
        import json as _json
        tags: list[str] = []
        summary_lines = raw.strip().splitlines()
        if summary_lines and summary_lines[-1].startswith("TAGS:"):
            tag_str = summary_lines[-1][5:].strip()
            try:
                tags = _json.loads(tag_str)
            except Exception:
                tags = []
            summary_lines = summary_lines[:-1]
        summary = "\n".join(summary_lines).strip()

        from proxi.memory.schema import EpisodeSummary
        episode = EpisodeSummary(
            agent_id=agent_id,
            session_id=session_id,
            summary=summary,
            full_text=transcript,
            tags=tags,
        )
        await memory_manager.save_episode(episode)
        logger.info(
            "session_summarized",
            agent_id=agent_id,
            session_id=session_id,
            tags=tags,
        )
    except Exception as exc:
        logger.warning("session_summarization_failed", error=str(exc))


def _should_emit_inbound_turn_header(event: GatewayEvent) -> bool:
    """Non-TUI sources (heartbeat, cron, webhooks, …) should show a synthetic prompt in the TUI."""
    st = event.source_type
    if st in ("heartbeat", "cron", "webhook"):
        return True
    if st in ("telegram", "whatsapp", "discord"):
        return True
    if st == "http":
        return event.source_id not in ("tui", "http")
    return False


class _SseEmitter:
    """Bridge emitter that forwards messages to all attached ``HttpSseReplyChannel`` instances."""

    def __init__(self, channels: dict[str, Any], *, tui_abortable: bool = False, source_id: str = "", source_type: str = "") -> None:
        self._channels = channels
        self._tui_abortable = tui_abortable
        self._source_id = source_id
        self._source_type = source_type

    def emit(self, msg: dict[str, Any]) -> None:
        payload = dict(msg)
        if payload.get("type") == "status_update":
            payload["tui_abortable"] = self._tui_abortable
        if self._source_id:
            payload.setdefault("source_id", self._source_id)
        if self._source_type:
            payload.setdefault("source_type", self._source_type)
        for channel in self._channels.values():
            try:
                channel._queue.put_nowait(payload)
            except Exception:
                pass


@dataclass
class AgentLane:
    session_id: str
    soul_path: Path
    history_path: Path
    workspace_config: WorkspaceConfig
    budget: LaneBudget

    queue: asyncio.PriorityQueue[tuple[int, float, GatewayEvent]] = field(
        default_factory=asyncio.PriorityQueue
    )
    _task: asyncio.Task[None] | None = field(default=None, repr=False)
    _loop: AgentLoop | None = field(default=None, repr=False)
    _state: AgentState | None = field(default=None, repr=False)
    _create_loop: Any = field(default=None, repr=False)  # factory callback
    _seq: int = field(default=0, repr=False)  # tie-breaker for priority queue

    # Active SSE subscribers for this lane (set by stream endpoint, keyed by subscriber_id)
    _sse_channels: dict[str, Any] = field(default_factory=dict, repr=False)
    _form_bridge: Any = field(default=None, repr=False)
    _running_task: asyncio.Task[str | None] | None = field(
        default=None, repr=False)
    _dispatch_tui_abortable: bool = field(default=False, repr=False)

    # Reasoning effort override set via /reasoning-effort command from the TUI.
    # Applied only to events from the TUI source; cron/discord/webhook events
    # always use "low" regardless of this setting.
    tui_reasoning_effort: str = field(default="low", repr=False)

    async def start(self) -> None:
        self._state = AgentState.load(self.history_path)
        self._task = asyncio.create_task(
            self._drain(), name=f"lane:{self.session_id}"
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, event: GatewayEvent) -> None:
        self._seq += 1
        await self.queue.put((-event.priority, self._seq, event))

    async def abort(self) -> None:
        """Cancel the active agent task and drain pending events."""
        if self._running_task is not None and not self._running_task.done():
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
        # Drain pending events
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break
        if self._sse_channels:
            await self._broadcast_sse(
                {
                    "type": "status_update",
                    "label": "Aborted",
                    "status": "done",
                    "tui_abortable": self._dispatch_tui_abortable,
                }
            )

    def try_resolve_pending_form_with_text(self, text: str) -> bool:
        """If the agent is blocked on ``ask_user_question``, map chat text to answers."""
        fb = self._form_bridge
        if fb is None or not hasattr(fb, "consume_chat_as_form_reply"):
            return False
        return bool(getattr(fb, "consume_chat_as_form_reply")(text))

    async def resume(self, form_answer: dict[str, Any]) -> None:
        """Unblock a SUSPENDED lane waiting on a form reply."""
        if self._form_bridge is not None and hasattr(self._form_bridge, "inject_answer"):
            await self._form_bridge.inject_answer(form_answer)
        elif self._loop is not None and self._loop.form_bridge is not None:
            bridge = self._loop.form_bridge
            if hasattr(bridge, "inject_answer"):
                # type: ignore[attr-defined]
                await bridge.inject_answer(form_answer)

    def attach_sse(self, channel: Any, subscriber_id: str = "sse", form_bridge: Any = None) -> None:
        """Attach an SSE channel for a named subscriber (e.g. 'tui', 'react')."""
        self._sse_channels[subscriber_id] = channel
        # TUI owns the form bridge; other subscribers don't override it.
        if subscriber_id == "tui" or self._form_bridge is None:
            self._form_bridge = form_bridge

    def detach_sse(self, channel: Any | None = None, subscriber_id: str | None = None) -> None:
        """Detach an SSE channel if it is still the active attachment for its subscriber.

        ``stream_session`` can reconnect quickly: an older stream's ``finally``
        may run after a newer stream already attached. In that case, ignore the
        stale detach so we do not drop live output for subsequent prompts.
        """
        if subscriber_id is not None:
            if self._sse_channels.get(subscriber_id) is not channel:
                return
            self._sse_channels.pop(subscriber_id, None)
        elif channel is not None:
            # Fallback: remove any subscriber whose channel matches
            to_remove = [k for k, v in self._sse_channels.items() if v is channel]
            for k in to_remove:
                self._sse_channels.pop(k)
        else:
            self._sse_channels.clear()
        if not self._sse_channels:
            self._form_bridge = None

    async def _broadcast_sse(self, event_dict: dict[str, Any]) -> None:
        """Send an SSE event to all attached subscribers."""
        for channel in list(self._sse_channels.values()):
            try:
                await channel.send_event(event_dict)
            except Exception:
                pass

    @property
    def queue_depth(self) -> int:
        return self.queue.qsize()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def sync_coding_tools(self, working_dir: Path) -> None:
        """Replace coding tools on an existing loop with ones rooted at *working_dir*."""
        if self._loop is None:
            return
        from proxi.tools.coding import unregister_coding_tools, register_coding_tools, FILESYSTEM_TOOL_NAMES
        from proxi.tools.filesystem import ReadFileTool, WriteFileTool
        from proxi.tools.path_guard import PathGuard

        reg = self._loop.tool_registry
        unregister_coding_tools(reg)

        # Also replace read_file / write_file which were
        # registered with the old working directory's PathGuard.
        for name in FILESYSTEM_TOOL_NAMES:
            reg._tools.pop(name, None)
            reg._schema_injected.discard(name)
        guard = PathGuard(working_dir)
        for tool in (ReadFileTool(guard=guard), WriteFileTool(guard=guard)):
            reg.register(tool)

        # Re-read tier from agent config so we respect the per-agent setting.
        try:
            from proxi.workspace import WorkspaceManager

            ws = self._loop.workspace  # type: ignore[attr-defined]
            agent_id = ws.agent_id if ws is not None else ""
            wm = WorkspaceManager(root=self.soul_path.parent.parent.parent)
            agent_cfg = wm.read_agent_config(agent_id)
            tier = str(agent_cfg.get("tool_sets", {}).get("coding", "live"))
        except Exception:
            tier = "live"
        register_coding_tools(reg, working_dir=working_dir, tier=tier)
        # Update workspace so the prompt builder sees the new cwd.
        if ws is not None:
            ws.curr_working_dir = str(working_dir)

    def sync_mcp_tools(
        self,
        mcp_tools: Sequence[Any],
        deferred_tools: Sequence[Any] = (),
    ) -> None:
        """Replace MCP-backed tools on an existing loop (stdio clients are per-refresh)."""
        if self._loop is None:
            return
        reg = self._loop.tool_registry
        reg.unregister_by_prefix("mcp_")
        reg.unregister_by_prefix("search_tools")
        reg.unregister_by_prefix("call_tool")
        for tool in mcp_tools:
            reg.register(tool)
        for tool in deferred_tools:
            reg.register_deferred(tool)
        if reg.has_deferred_tools():
            from proxi.tools.call_tool_tool import CallToolTool
            reg.register(CallToolTool(reg))

    def _sync_state_if_history_cleared(self) -> None:
        """Align memory with disk when history.jsonl is empty (e.g. /clear raced ahead of _state reset)."""
        try:
            if self.history_path.exists() and self.history_path.stat().st_size > 0:
                return
        except OSError:
            return
        if self._state is not None and self._state.history:
            self._state = None
            self.budget.reset()
            self._loop = None

    async def clear_session_history(self) -> None:
        """Stop work, wipe ``history.jsonl``, reset in-memory state (fresh chat; prompts unchanged)."""
        await self.abort()
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text("", encoding="utf-8")
        self._state = None
        self.budget.reset()
        self._loop = None

    async def reset_loop(self) -> None:
        """Recreate the runtime loop while keeping session history in memory."""
        await self.abort()
        self._loop = None

    async def _drain(self) -> None:
        """Core loop — processes events one at a time, serialising within the session."""
        while True:
            _, _, event = await self.queue.get()
            try:
                self._running_task = asyncio.ensure_future(
                    self._dispatch(event))
                response = await self._running_task
                if event.reply_channel and response:
                    await event.reply_channel.send(response)
                elif event.reply_channel and not response:
                    logger.warning("lane_reply_skipped_no_response",
                                   session=self.session_id, source=event.source_type)
                if event.broadcast_reply_channels and response:
                    for brc in event.broadcast_reply_channels:
                        try:
                            await brc.send(response)
                        except Exception:
                            logger.warning("broadcast_reply_failed",
                                           session=self.session_id, dest=brc.destination)
            except asyncio.CancelledError:
                logger.info("lane_dispatch_aborted", session=self.session_id)
            except BudgetExceeded as exc:
                # Attempt compaction before hard-stopping, then re-enqueue the event.
                if (
                    self._loop is not None
                    and self._loop.compactor is not None
                    and self._state is not None
                ):
                    try:
                        compact_result = await self._loop.compactor.force_compact(
                            self._state,
                            current_tokens=self.budget.tokens_used,
                        )
                        if compact_result.compaction_triggered:
                            self.budget.tokens_used = 0
                            self._seq += 1
                            await self.queue.put((0, self._seq, event))
                            logger.info(
                                "lane_budget_compacted_requeued",
                                session=self.session_id,
                                from_tokens=compact_result.original_tokens,
                            )
                            continue  # back to drain loop; event will be retried
                    except Exception:
                        pass  # fall through to hard-stop

                logger.warning(
                    "lane_budget_exceeded",
                    session=self.session_id,
                    event_id=event.event_id,
                    detail=str(exc),
                )
                if event.reply_channel:
                    await event.reply_channel.send(f"I hit a limit: {exc}")
                self.budget.reset()
            except Exception:
                logger.exception(
                    "lane_dispatch_error",
                    session=self.session_id,
                    event_id=event.event_id,
                )
                if self._sse_channels:
                    await self._broadcast_sse(
                        {
                            "type": "text_stream",
                            "content": "[Error: request failed in lane dispatch]",
                        }
                    )
                    await self._broadcast_sse(
                        {
                            "type": "status_update",
                            "label": "Failed",
                            "status": "done",
                            "tui_abortable": self._dispatch_tui_abortable,
                        }
                    )
                elif event.reply_channel:
                    try:
                        await event.reply_channel.send("Sorry, something went wrong processing your request.")
                    except Exception:
                        pass
            finally:
                self._running_task = None
                self.queue.task_done()

    async def _dispatch(self, event: GatewayEvent) -> str | None:
        self._sync_state_if_history_cleared()
        if self._loop is None:
            if self._create_loop is not None:
                self._loop = self._create_loop(self.workspace_config)
            else:
                raise RuntimeError("AgentLane._create_loop factory not set")

        tui_abortable = event.source_id == "tui"
        self._dispatch_tui_abortable = tui_abortable

        # Attach SSE emitter + form bridge when at least one SSE subscriber is connected
        if self._sse_channels:
            self._loop.emitter = _SseEmitter(
                dict(self._sse_channels), tui_abortable=tui_abortable,
                source_id=event.source_id, source_type=event.source_type,
            )
            if self._form_bridge is not None:
                self._loop.form_bridge = self._form_bridge

        # Workspace is not persisted in history.jsonl — re-attach it so the
        # PromptBuilder can build the system prompt (profile, soul, etc.).
        if self._state is not None and self._state.workspace is None:
            self._state.workspace = self.workspace_config

        text = event.payload.get("text", "").strip()

        # Handle /compact [focus] as a lane-level command — never sent to the loop.
        if text.lower().startswith("/compact"):
            focus = text[len("/compact"):].strip() or None
            if self._sse_channels:
                await self._broadcast_sse({
                    "type": "status_update",
                    "label": "Compacting",
                    "status": "running",
                    # Compaction is lane-level maintenance; do not show Esc-abort affordance.
                    "tui_abortable": False,
                })
            try:
                if self._loop is not None and self._loop.compactor is not None and self._state is not None:
                    result = await self._loop.compactor.force_compact(
                        self._state,
                        current_tokens=self.budget.tokens_used,
                        focus=focus,
                    )
                    if result.compaction_triggered:
                        self.budget.tokens_used = 0  # reset; real count updates after next API call
                    focus_note = f' Focus: "{focus}"' if focus else ""
                    if self._sse_channels:
                        if result.compaction_triggered:
                            content = (
                                f"Context compacted.{focus_note} "
                                f"~{result.original_tokens} → ~{result.compacted_token_estimate} tokens."
                            )
                        else:
                            history_len = len(
                                self._state.history) if self._state else 0
                            content = (
                                f"Nothing to compact — history is too short ({history_len} messages). "
                                "Have a longer conversation and try again."
                            )
                        await self._broadcast_sse({
                            "type": "text_stream",
                            "content": content,
                        })
                        await self._broadcast_sse({
                            "type": "status_update",
                            "label": "Compacted",
                            "status": "done",
                            "tui_abortable": False,
                        })
                elif self._sse_channels:
                    await self._broadcast_sse({
                        "type": "text_stream",
                        "content": "Compaction unavailable for this session.",
                    })
                    await self._broadcast_sse({
                        "type": "status_update",
                        "label": "Compacted",
                        "status": "done",
                        "tui_abortable": False,
                    })
            except Exception as exc:
                logger.exception(
                    "lane_compaction_failed",
                    session=self.session_id,
                    event_id=event.event_id,
                    error=str(exc),
                )
                if self._sse_channels:
                    await self._broadcast_sse({
                        "type": "text_stream",
                        "content": "Compaction failed. I left your session history unchanged.",
                    })
                    await self._broadcast_sse({
                        "type": "status_update",
                        "label": "Compaction failed",
                        "status": "done",
                        "tui_abortable": False,
                    })
            return None

        # Handle /reasoning-effort <level> as a lane-level command — never sent to the loop.
        # Only affects events that originate from the TUI; all other sources always use "minimal".
        if text.lower().startswith("/reasoning-effort"):
            level = text[len("/reasoning-effort"):].strip().lower()
            if level == "reset":
                level = "low"
            _valid_levels = {"minimal", "low", "medium", "high"}
            if level in _valid_levels:
                self.tui_reasoning_effort = level
                _re_label = (
                    f"Reasoning effort → {level}"
                    if level != "low"
                    else "Reasoning effort → low (default)"
                )
            else:
                _re_label = f"Unknown level '{level}' — use: minimal · low · medium · high"
            # Intentionally don't emit a TUI text_stream line for this lane-level setting.
            # The TUI already shows the active effort level in the status bar.
            return None

        # Handle /plan [goal] and /plan refine [feedback] as lane-level plan-mode commands.
        # Unlike /compact, these ARE forwarded to the loop (plan mode drives agent behaviour).
        if text.lower().startswith("/plan"):
            rest = text[len("/plan"):].strip()

            if rest.lower().startswith("refine"):
                # /plan refine {feedback} — keep plan_mode active, pass feedback to loop
                feedback = rest[len("refine"):].strip()
                if self._state is not None:
                    self._state.plan_mode = True
                    self._state.reasoning_effort = "medium"
                # Ensure active_plan_path stays set during refine cycles
                _active_plan = str(
                    Path(self.workspace_config.workspace_root)
                    / "agents" / self.workspace_config.agent_id / "plans" / "in-progress.md"
                )
                self.workspace_config.active_plan_path = _active_plan
                if self._state is not None and self._state.workspace is not None:
                    self._state.workspace.active_plan_path = _active_plan
                plan_instruction = (
                    "PLAN MODE — REFINE. The user has reviewed the plan and wants changes.\n"
                    f"User feedback: {feedback}\n\n"
                    "Update plan.md via manage_plan to reflect the feedback, then respond with a brief summary."
                )
                text = plan_instruction

            else:
                # /plan {goal} — enter plan mode
                goal = rest
                # Point manage_plan at plans/in-progress.md so the plan lives in plans/ from the start
                _active_plan = str(
                    Path(self.workspace_config.workspace_root)
                    / "agents" / self.workspace_config.agent_id / "plans" / "in-progress.md"
                )
                self.workspace_config.active_plan_path = _active_plan
                if self._state is not None:
                    self._state.plan_mode = True
                    self._state.reasoning_effort = "medium"
                    if self._state.workspace is not None:
                        self._state.workspace.active_plan_path = _active_plan
                plan_instruction = (
                    "PLAN MODE ACTIVE. You are now in an interactive planning session.\n\n"
                    "Your job:\n"
                    "1. Use ask_user_question to interview the user and deeply understand their goal, "
                    "requirements, and constraints. Ask at most 6 focused, non-redundant questions per "
                    "call — prioritise the most critical unknowns first. If you still need more context "
                    "after the user responds, make a follow-up call with the remaining questions.\n"
                    "2. Use only read-only tools (read_file, glob, grep, manage_plan for reading) "
                    "to explore the codebase and gather context.\n"
                    "3. Once you have a thorough understanding, write a comprehensive, structured plan "
                    "to plan.md using manage_plan(content=...).\n"
                    "4. Respond with a brief summary when you are done writing the plan.\n\n"
                    "MARKDOWN FORMATTING — the plan is a .md file rendered with full markdown support. "
                    "You MUST use markdown syntax throughout:\n"
                    "- Use # / ## / ### headings to structure sections.\n"
                    "- Use ``` fenced code blocks (with a language tag, e.g. ```python, ```shell, ```typescript) "
                    "for ALL code snippets, shell commands, file content, diffs, and pseudo-code.\n"
                    "- Use `backtick` inline spans for file paths, function names, variable names, "
                    "flags, and any other technical tokens mentioned in prose.\n"
                    "- Use - bullet lists and 1. numbered lists for steps and sub-tasks.\n"
                    "- Use - [ ] / - [x] checkboxes for actionable implementation steps.\n\n"
                    "IMPORTANT: Write operations on any files other than manage_plan are blocked in plan mode.\n\n"
                    f"User goal: {goal}"
                )
                text = plan_instruction
                if self._sse_channels:
                    await self._broadcast_sse({
                        "type": "status_update",
                        "label": "Planning",
                        "status": "running",
                        "tui_abortable": True,
                    })

        if self._sse_channels and _should_emit_inbound_turn_header(event):
            await self._broadcast_sse(
                {
                    "type": "inbound_turn",
                    "source_type": event.source_type,
                    "source_id": event.source_id,
                    "prompt": text,
                }
            )

        # Compute effective reasoning effort for this dispatch:
        #   1. Plan mode (active or entering) always uses "medium".
        #   2. TUI-sourced events use the user-configured tui_reasoning_effort (default: "low").
        #   3. All other sources (cron, discord, webhook, …) always use "minimal" for speed.
        _entering_plan_mode = text.startswith("PLAN MODE")
        _already_plan_mode = self._state is not None and self._state.plan_mode
        if _entering_plan_mode or _already_plan_mode:
            _effective_effort = "medium"
        elif event.source_id == "tui":
            _effective_effort = self.tui_reasoning_effort
        else:
            _effective_effort = "minimal"

        if self._state is not None and self._state.history:
            self._state.reasoning_effort = _effective_effort
            result_state = await self._loop.run_continue(self._state, text)
        else:
            # Fresh session — pass reasoning_effort directly so the new AgentState
            # is created with the correct value instead of the "low" default.
            result_state = await self._loop.run(text, reasoning_effort=_effective_effort)

        # For existing-session run_continue(), reasoning_effort was already set on
        # self._state before the call.  Retroactively apply plan_mode flag so that
        # plan_ready emission and subsequent refine turns see the correct state.
        if _entering_plan_mode:
            result_state.plan_mode = True

        # Reset reasoning effort to "low" once the loop finishes a non-plan-mode turn.
        # This ensures "medium" effort only covers the plan-writing and plan-execution runs,
        # not all subsequent user messages in the session.
        if not result_state.plan_mode:
            result_state.reasoning_effort = "low"

        self._state = result_state
        last_turn_tokens = result_state.turns[-1].tokens_used if result_state.turns else 0
        self.budget.record_turn(context_tokens=last_turn_tokens)

        # If in plan mode and plan file has content, emit plan_ready before Done.
        if result_state.plan_mode and result_state.workspace and self._sse_channels:
            try:
                _ppath = result_state.workspace.active_plan_path or result_state.workspace.plan_path
                plan_path = Path(_ppath)
                if plan_path.exists() and plan_path.stat().st_size > 0:
                    plan_content = plan_path.read_text(encoding="utf-8")
                    await self._broadcast_sse({
                        "type": "plan_ready",
                        "content": plan_content,
                        # Session plan.md path (typically sessions/<session_id>/plan.md)
                        "plan_path": result_state.workspace.plan_path,
                        # When plan mode is active, the agent may be writing to an in-progress file.
                        "active_plan_path": result_state.workspace.active_plan_path,
                    })
            except Exception:
                pass

        # Signal completion on all SSE subscribers
        if self._sse_channels:
            await self._broadcast_sse(
                {
                    "type": "status_update",
                    "label": "Done",
                    "status": "done",
                    "tui_abortable": tui_abortable,
                }
            )

        # Fire-and-forget post-session summarization into episodic memory
        try:
            from proxi.gateway import server as _srv
            _mm = getattr(_srv, "memory_manager", None)
            if _mm is not None and self._loop is not None:
                _ws = result_state.workspace
                _agent_id = _ws.agent_id if _ws else "unknown"
                _session_id = _ws.session_id if _ws else self.session_id
                if _mm.is_enabled(_agent_id):
                    asyncio.ensure_future(
                        _summarize_session(
                            agent_id=_agent_id,
                            session_id=_session_id,
                            history=list(result_state.history),
                            memory_manager=_mm,
                            llm_client=self._loop.llm_client,
                        )
                    )
        except Exception:
            pass  # never block the dispatch path

        last_msg = (
            result_state.history[-1]
            if result_state.history
            else None
        )
        if last_msg and last_msg.role == "assistant" and last_msg.content:
            return last_msg.content
        return None
