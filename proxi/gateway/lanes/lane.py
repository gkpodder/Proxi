"""AgentLane — asyncio queue + processing task per session."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from proxi.core.loop import AgentLoop
from proxi.core.state import AgentState, WorkspaceConfig
from proxi.gateway.events import GatewayEvent
from proxi.gateway.lanes.budget import BudgetExceeded, LaneBudget
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


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
    """Bridge emitter that forwards messages to an ``HttpSseReplyChannel``."""

    def __init__(self, channel: Any, *, tui_abortable: bool = False) -> None:
        self._channel = channel
        self._tui_abortable = tui_abortable

    def emit(self, msg: dict[str, Any]) -> None:
        try:
            payload = dict(msg)
            if payload.get("type") == "status_update":
                payload["tui_abortable"] = self._tui_abortable
            self._channel._queue.put_nowait(payload)
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

    # Active SSE channel for this lane (set by stream endpoint)
    _sse_channel: Any = field(default=None, repr=False)
    _form_bridge: Any = field(default=None, repr=False)
    _running_task: asyncio.Task[str | None] | None = field(default=None, repr=False)
    _dispatch_tui_abortable: bool = field(default=False, repr=False)

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
        if self._sse_channel is not None:
            try:
                await self._sse_channel.send_event(
                    {
                        "type": "status_update",
                        "label": "Aborted",
                        "status": "done",
                        "tui_abortable": self._dispatch_tui_abortable,
                    }
                )
            except Exception:
                pass

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
                await bridge.inject_answer(form_answer)  # type: ignore[attr-defined]

    def attach_sse(self, channel: Any, form_bridge: Any = None) -> None:
        """Attach an SSE channel (and optional form bridge) to this lane."""
        self._sse_channel = channel
        self._form_bridge = form_bridge

    def detach_sse(self, channel: Any | None = None) -> None:
        """Detach SSE channel if it is still the active attachment.

        ``stream_session`` can reconnect quickly: an older stream's ``finally``
        may run after a newer stream already attached. In that case, ignore the
        stale detach so we do not drop live output for subsequent prompts.
        """
        if channel is not None and self._sse_channel is not channel:
            return
        self._sse_channel = None
        self._form_bridge = None

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
                self._running_task = asyncio.ensure_future(self._dispatch(event))
                response = await self._running_task
                if event.reply_channel and response:
                    await event.reply_channel.send(response)
                elif event.reply_channel and not response:
                    logger.warning("lane_reply_skipped_no_response", session=self.session_id, source=event.source_type)
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
                if self._sse_channel is not None:
                    try:
                        await self._sse_channel.send_event(
                            {
                                "type": "text_stream",
                                "content": "[Error: request failed in lane dispatch]",
                            }
                        )
                        await self._sse_channel.send_event(
                            {
                                "type": "status_update",
                                "label": "Failed",
                                "status": "done",
                                "tui_abortable": self._dispatch_tui_abortable,
                            }
                        )
                    except Exception:
                        pass
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

        # Attach SSE emitter + form bridge when an SSE listener is connected
        if self._sse_channel is not None:
            self._loop.emitter = _SseEmitter(
                self._sse_channel, tui_abortable=tui_abortable
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
            if self._sse_channel is not None:
                try:
                    await self._sse_channel.send_event({
                        "type": "status_update",
                        "label": "Compacting",
                        "status": "running",
                        # Compaction is lane-level maintenance; do not show Esc-abort affordance.
                        "tui_abortable": False,
                    })
                except Exception:
                    pass
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
                    if self._sse_channel is not None:
                        try:
                            if result.compaction_triggered:
                                content = (
                                    f"Context compacted.{focus_note} "
                                    f"~{result.original_tokens} → ~{result.compacted_token_estimate} tokens."
                                )
                            else:
                                history_len = len(self._state.history) if self._state else 0
                                content = (
                                    f"Nothing to compact — history is too short ({history_len} messages). "
                                    "Have a longer conversation and try again."
                                )
                            await self._sse_channel.send_event({
                                "type": "text_stream",
                                "content": content,
                            })
                            await self._sse_channel.send_event({
                                "type": "status_update",
                                "label": "Compacted",
                                "status": "done",
                                "tui_abortable": False,
                            })
                        except Exception:
                            pass
                elif self._sse_channel is not None:
                    try:
                        await self._sse_channel.send_event({
                            "type": "text_stream",
                            "content": "Compaction unavailable for this session.",
                        })
                        await self._sse_channel.send_event({
                            "type": "status_update",
                            "label": "Compacted",
                            "status": "done",
                            "tui_abortable": False,
                        })
                    except Exception:
                        pass
            except Exception as exc:
                logger.exception(
                    "lane_compaction_failed",
                    session=self.session_id,
                    event_id=event.event_id,
                    error=str(exc),
                )
                if self._sse_channel is not None:
                    try:
                        await self._sse_channel.send_event({
                            "type": "text_stream",
                            "content": "Compaction failed. I left your session history unchanged.",
                        })
                        await self._sse_channel.send_event({
                            "type": "status_update",
                            "label": "Compaction failed",
                            "status": "done",
                            "tui_abortable": False,
                        })
                    except Exception:
                        pass
            return None

        if (
            self._sse_channel is not None
            and _should_emit_inbound_turn_header(event)
        ):
            try:
                await self._sse_channel.send_event(
                    {
                        "type": "inbound_turn",
                        "source_type": event.source_type,
                        "source_id": event.source_id,
                        "prompt": text,
                    }
                )
            except Exception:
                pass

        if self._state is not None and self._state.history:
            result_state = await self._loop.run_continue(self._state, text)
        else:
            result_state = await self._loop.run(text)

        self._state = result_state
        last_turn_tokens = result_state.turns[-1].tokens_used if result_state.turns else 0
        self.budget.record_turn(context_tokens=last_turn_tokens)

        # Signal completion on the SSE channel
        if self._sse_channel is not None:
            try:
                await self._sse_channel.send_event(
                    {
                        "type": "status_update",
                        "label": "Done",
                        "status": "done",
                        "tui_abortable": tui_abortable,
                    }
                )
            except Exception:
                pass

        last_msg = (
            result_state.history[-1]
            if result_state.history
            else None
        )
        if last_msg and last_msg.role == "assistant" and last_msg.content:
            return last_msg.content
        return None
