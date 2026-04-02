"""
Headless bridge for the proxi agent: JSON-RPC over stdin/stdout for TUI clients.
"""

import asyncio
import hashlib
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

from proxi.interaction.tool import get_ask_user_question_spec
from proxi.tools.workspace_tools import ManagePlanTool, ManageTodosTool, ReadSoulTool
from proxi.cli.main import (
    auto_load_mcp_servers,
    create_llm_client,
    setup_mcp,
    setup_sub_agents,
    setup_tools,
)
from proxi.core.loop import AgentLoop
from proxi.core.state import AgentState
from proxi.observability.logging import get_logger, init_log_manager
from proxi.observability.perf import elapsed_ms, emit_perf, now_ns, perf_enabled
from proxi.security.key_store import enable_mcp, list_mcps
from proxi.workspace import WorkspaceManager

logger = get_logger(__name__)


class StdioEmitter:
    """Emits bridge messages as JSON lines to stdout."""

    def __init__(self) -> None:
        self._closed = False
        self._last_status: tuple[str, str] | None = None
        self._max_emit_bytes = int(os.getenv("PROXI_BRIDGE_MAX_EMIT_BYTES", "0"))
        self._queue_maxsize = max(100, int(os.getenv("PROXI_BRIDGE_OUTBOUND_MAX_QUEUE", "2000")))
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=self._queue_maxsize)
        self._worker = threading.Thread(target=self._drain_loop, name="proxi-bridge-emitter", daemon=True)
        self._worker.start()

    def _emit_perf_safe(self, event: str, **fields: Any) -> None:
        # Keep test stdout pure when monkeypatched to an in-memory stream.
        if not perf_enabled():
            return
        if hasattr(sys.stdout, "getvalue"):
            return
        emit_perf(event, **fields)

    def _direct_emit(self, msg: dict[str, Any]) -> None:
        emit_start_ns = now_ns()
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        if self._max_emit_bytes > 0 and len(line.encode("utf-8")) > self._max_emit_bytes:
            self._emit_perf_safe(
                "perf_bridge_emit_dropped",
                reason="oversize",
                msg_type=msg.get("type"),
                bytes=len(line.encode("utf-8")),
            )
            return
        sys.stdout.write(line)
        sys.stdout.flush()
        self._emit_perf_safe(
            "perf_bridge_emit",
            msg_type=msg.get("type"),
            bytes=len(line.encode("utf-8")),
            elapsed_ms=round(elapsed_ms(emit_start_ns), 3),
            queue_depth=self._queue.qsize(),
        )

    def _drain_loop(self) -> None:
        while not self._closed:
            try:
                msg = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg.get("type") == "__close__":
                return
            try:
                self._direct_emit(msg)
            except (BrokenPipeError, OSError):
                self._closed = True
                return

    def emit(self, msg: dict[str, Any]) -> None:
        if self._closed:
            return
        if os.getenv("PROXI_BRIDGE_EMIT_SYNC", "0").strip().lower() in {"1", "true", "yes"}:
            try:
                self._direct_emit(msg)
            except (BrokenPipeError, OSError):
                self._closed = True
            return
        if msg.get("type") in {"ready"}:
            try:
                self._direct_emit(msg)
            except (BrokenPipeError, OSError):
                self._closed = True
            return
        if msg.get("type") == "status_update":
            status_key = (str(msg.get("label", "")), str(msg.get("status", "")))
            if self._last_status == status_key:
                self._emit_perf_safe("perf_bridge_emit_dropped", reason="duplicate_status")
                return
            self._last_status = status_key
        try:
            self._queue.put_nowait(msg)
            depth = self._queue.qsize()
            high_watermark = int(os.getenv("PROXI_BRIDGE_QUEUE_HIGH_WATERMARK", "1500"))
            if depth >= high_watermark:
                self._emit_perf_safe(
                    "perf_budget_exceeded",
                    component="bridge_emitter",
                    budget="queue_depth",
                    value=depth,
                    threshold=high_watermark,
                )
        except queue.Full:
            # Backpressure policy: drop low-priority status/text stream messages first.
            if msg.get("type") in {"status_update", "text_stream", "tool_log"}:
                self._emit_perf_safe(
                    "perf_bridge_emit_dropped",
                    reason="queue_full_low_priority",
                    msg_type=msg.get("type"),
                    queue_depth=self._queue.qsize(),
                )
                return
            # High-priority event fallback: direct best-effort emit.
            self._emit_perf_safe(
                "perf_bridge_emit_backpressure",
                reason="queue_full_fallback_direct",
                msg_type=msg.get("type"),
                queue_depth=self._queue.qsize(),
            )
            try:
                self._direct_emit(msg)
            except (BrokenPipeError, OSError):
                self._closed = True

    def close(self) -> None:
        """Close emitter worker and stop future emits."""
        self._closed = True
        try:
            self._queue.put_nowait({"type": "__close__"})
        except queue.Full:
            pass
        if self._worker.is_alive():
            self._worker.join(timeout=0.5)


async def run_bridge(agent_id: str | None = None) -> None:
    """Run the bridge: read JSON commands from stdin, run agent, emit to stdout."""
    # When piped (e.g. by TUI), use line buffering so we see input/output immediately
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if not sys.stdin.isatty() and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(line_buffering=True)

    working_dir = Path(os.environ.get("PROXI_WORKING_DIR", ".")).resolve()

    # Initialize log manager for TUI session
    log_manager = init_log_manager(base_dir=working_dir / "logs")
    log_manager.configure_logging(level=os.environ.get(
        "LOG_LEVEL", "INFO"), use_colors=False)

    logger.info("initializing_bridge", log_dir=str(
        log_manager.get_session_dir()))
    provider = os.environ.get("PROXI_PROVIDER", "openai").lower()
    max_turns = int(os.environ.get("PROXI_MAX_TURNS", "20"))
    mcp_server = os.environ.get("PROXI_MCP_SERVER")
    no_sub_agents = os.environ.get(
        "PROXI_NO_SUB_AGENTS", "").lower() in ("1", "true", "yes")

    try:
        logger.info("initializing_llm", provider=provider)
        llm_client = create_llm_client(provider=provider)
    except ValueError as e:
        sys.stderr.write(f"Bridge config error: {e}\n")
        sys.stderr.flush()
        sys.exit(1)

    logger.info("setting_up_tools")
    tool_registry = setup_tools(working_directory=working_dir)
    tool_registry.register_raw_spec(get_ask_user_question_spec())
    if no_sub_agents:
        sub_agent_manager = None
    else:
        logger.info("setting_up_sub_agents")
        sub_agent_manager = setup_sub_agents(llm_client)

    emitter = StdioEmitter()

    # Workspace manager for global/agent/session layout
    workspace_manager = WorkspaceManager()
    workspace_manager.ensure_global_system_prompt()

    # Queues for command messages, user_input (bootstrap), and form responses
    command_queue: asyncio.Queue[tuple[float, dict[str, Any] | None]] = asyncio.Queue()
    user_input_queue: asyncio.Queue[tuple[float, dict[str, Any] | None]] = asyncio.Queue()
    form_response_queue: asyncio.Queue[tuple[float, dict[str, Any] | None]] = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def stdin_reader() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                msg_type = obj.get("type")
                if msg_type == "user_input":
                    main_loop.call_soon_threadsafe(
                        user_input_queue.put_nowait, (time.monotonic(), obj))
                elif msg_type == "user_input_response":
                    main_loop.call_soon_threadsafe(
                        form_response_queue.put_nowait, (time.monotonic(), obj))
                else:
                    main_loop.call_soon_threadsafe(
                        command_queue.put_nowait, (time.monotonic(), obj))
            except json.JSONDecodeError:
                continue
        main_loop.call_soon_threadsafe(command_queue.put_nowait, (time.monotonic(), None))
        main_loop.call_soon_threadsafe(user_input_queue.put_nowait, (time.monotonic(), None))
        main_loop.call_soon_threadsafe(form_response_queue.put_nowait, (time.monotonic(), None))

    async def run_reader() -> None:
        await asyncio.to_thread(stdin_reader)

    asyncio.create_task(run_reader())

    class FormBridgeImpl:
        """Form bridge: emits user_input_required and awaits user_input_response."""

        async def request_form(
            self, tool_call_id: str, form_request: Any
        ) -> dict[str, Any]:
            emitter.emit({
                "type": "user_input_required",
                "payload": {
                    "tool_call_id": tool_call_id,
                    "goal": form_request.goal,
                    "title": form_request.title,
                    "questions": [q.model_dump(exclude_none=True) for q in form_request.questions],
                    "allow_skip": form_request.allow_skip,
                },
            })
            while True:
                queued_at, msg = await form_response_queue.get()
                emit_perf(
                    "perf_bridge_queue_wait",
                    queue="form_response",
                    wait_ms=round((time.monotonic() - queued_at) * 1000.0, 3),
                    depth=form_response_queue.qsize(),
                )
                if msg is None:
                    raise asyncio.CancelledError("Input stream closed")
                payload = msg.get("payload", msg)
                if payload.get("tool_call_id") == tool_call_id:
                    return payload

    form_bridge = FormBridgeImpl()

    # Create initial agent loop (workspace will be attached after bootstrap)
    loop = AgentLoop(
        llm_client=llm_client,
        tool_registry=tool_registry,
        sub_agent_manager=sub_agent_manager,
        max_turns=max_turns,
        enable_reflection=True,
        emitter=emitter,
        form_bridge=form_bridge,
        workspace=None,
    )

    # Tell TUI we are ready to accept commands (before slow MCP setup)
    emitter.emit({"type": "ready"})

    mcp_adapters = []
    last_mcp_signature: str | None = None
    
    # Auto-load configured MCP servers unless explicitly disabled
    no_mcp = os.environ.get("PROXI_NO_MCP", "").lower() in ("1", "true", "yes")
    if not no_mcp:
        try:
            logger.info("auto_loading_mcp_servers")
            mcp_adapters = await asyncio.wait_for(auto_load_mcp_servers(tool_registry), timeout=15.0)
            logger.info("mcp_servers_loaded", count=len(mcp_adapters))
        except asyncio.TimeoutError:
            logger.warning("mcp_auto_load_timeout")
        except Exception as e:
            logger.warning("mcp_auto_load_error", error=str(e))
    
    # Also support explicit MCP server via environment variable
    if mcp_server:
        try:
            mcp_adapter = await asyncio.wait_for(setup_mcp(mcp_server), timeout=10.0)
            if mcp_adapter:
                mcp_adapters.append(mcp_adapter)
                for tool in await mcp_adapter.get_tools():
                    tool_registry.register(tool)
        except asyncio.TimeoutError:
            logger.warning("mcp_setup_timeout", server=mcp_server)
        except Exception as e:
            logger.warning("mcp_setup_error", error=str(e))

    # Register call_tool if any tools were deferred
    if tool_registry.has_deferred_tools():
        from proxi.tools.call_tool_tool import CallToolTool
        tool_registry.register(CallToolTool(tool_registry))
        logger.info("call_tool_registered", deferred_count=tool_registry.deferred_tool_count())

    async def refresh_mcp_tools() -> None:
        """Reload MCP tools from currently enabled MCPs without restarting bridge."""
        nonlocal mcp_adapters
        nonlocal last_mcp_signature
        from proxi.cli.main import load_mcp_config
        from proxi.security.key_store import get_enabled_mcps

        no_mcp_local = os.environ.get("PROXI_NO_MCP", "").lower() in ("1", "true", "yes")
        if no_mcp_local:
            return
        signature_payload = {
            "enabled": sorted(get_enabled_mcps()),
            "config": load_mcp_config(),
            "explicit_server": mcp_server,
        }
        signature = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if signature == last_mcp_signature:
            emit_perf("perf_mcp_refresh_skipped", reason="unchanged_config")
            return
        last_mcp_signature = signature

        # Remove previously registered MCP tools (and search_tools), then re-load.
        removed = tool_registry.unregister_by_prefix("mcp_")
        if removed:
            logger.info("mcp_tools_unregistered", count=removed)
        # Remove search_tools + call_tool so they can be re-registered with the updated registry
        tool_registry.unregister_by_prefix("search_tools")
        tool_registry.unregister_by_prefix("call_tool")

        for adapter in mcp_adapters:
            try:
                await asyncio.wait_for(adapter.close(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("mcp_close_timeout")
            except Exception as e:
                logger.warning("mcp_close_error", error=str(e))
        mcp_adapters = []

        try:
            logger.info("refreshing_mcp_servers")
            mcp_adapters = await asyncio.wait_for(auto_load_mcp_servers(tool_registry), timeout=15.0)
            logger.info("mcp_servers_reloaded", count=len(mcp_adapters))
        except asyncio.TimeoutError:
            logger.warning("mcp_refresh_timeout")
        except Exception as e:
            logger.warning("mcp_refresh_error", error=str(e))

        if mcp_server:
            try:
                mcp_adapter = await asyncio.wait_for(setup_mcp(mcp_server), timeout=10.0)
                if mcp_adapter:
                    mcp_adapters.append(mcp_adapter)
                    for tool in await mcp_adapter.get_tools():
                        tool_registry.register(tool)
            except asyncio.TimeoutError:
                logger.warning("mcp_setup_timeout", server=mcp_server)
            except Exception as e:
                logger.warning("mcp_setup_error", error=str(e))

        # Re-register call_tool if deferred tools exist after refresh
        if tool_registry.has_deferred_tools():
            from proxi.tools.call_tool_tool import CallToolTool
            tool_registry.register(CallToolTool(tool_registry))
            logger.info("call_tool_re_registered", deferred_count=tool_registry.deferred_tool_count())

    async def request_user_input(
        method: str,
        prompt: str,
        options: list[str] | None = None,
    ) -> Any:
        """Emit a user_input_required message and wait for a user_input response."""
        emitter.emit(
            {
                "type": "user_input_required",
                "method": method,
                "prompt": prompt,
                "options": options or [],
            }
        )
        while True:
            queued_at, cmd = await user_input_queue.get()
            emit_perf(
                "perf_bridge_queue_wait",
                queue="user_input",
                wait_ms=round((time.monotonic() - queued_at) * 1000.0, 3),
                depth=user_input_queue.qsize(),
            )
            if cmd is None:
                raise asyncio.CancelledError("Input stream closed")
            if cmd.get("type") == "user_input":
                return cmd.get("value")

    async def manage_mcps_interactively() -> None:
        """Interactive MCP enable/disable workflow for the TUI."""
        done_label = "[Done]"

        while True:
            records = list_mcps()
            records = sorted(records, key=lambda r: r.mcp_name)
            options = [
                (
                    f"{r.mcp_name} [{'Enabled' if r.enabled else 'Disabled'}] "
                    f"-> {'Disable' if r.enabled else 'Enable'}"
                )
                for r in records
            ]
            options.append(done_label)

            choice = await request_user_input(
                "select",
                "MCP Settings: choose an MCP to toggle, or select [Done]",
                options=options,
            )
            choice_str = str(choice)

            if choice_str == done_label:
                emitter.emit({
                    "type": "text_stream",
                    "content": "MCP settings updated.\n",
                })
                break

            selected_index = next(
                (idx for idx, option in enumerate(options[:-1]) if option == choice_str),
                None,
            )
            if selected_index is None:
                continue

            selected = records[selected_index]
            new_enabled = not selected.enabled
            enable_mcp(selected.mcp_name, enabled=new_enabled)

            await refresh_mcp_tools()

            emitter.emit(
                {
                    "type": "text_stream",
                    "content": (
                        f"MCP '{selected.mcp_name}' "
                        f"{'enabled' if new_enabled else 'disabled'}.\n"
                    ),
                }
            )

    async def bootstrap_workspace(force_interactive: bool = False) -> tuple[WorkspaceManager, Any]:
        """Select or create an agent and single-session workspace.

        If force_interactive is True, ignore any CLI-provided agent_id and
        always drive selection/creation via TUI prompts.
        """

        async def create_agent_interactively() -> Any:
            """Run the interactive identity flow to create a new agent."""
            name = await request_user_input("text", "Enter a name for this agent:")
            persona = await request_user_input(
                "text",
                "Briefly describe this agent's persona/voice:",
            )
            return workspace_manager.create_agent(
                name=str(name or "Proxi"),
                persona=str(persona or "Helpful, patient, and clear."),
            )

        # Discover existing agents
        agents = workspace_manager.list_agents()
        agent_info = None

        if agent_id and not force_interactive:
            # Non-interactive: prefer explicit agent_id
            for a in agents:
                if a.agent_id == agent_id:
                    agent_info = a
                    break
            if agent_info is None:
                agent_info = workspace_manager.create_agent(
                    name=agent_id,
                    persona="General-purpose TUI agent.",
                    agent_id=agent_id,
                )
        else:
            create_label = "[+] Create new agent"
            if not agents:
                # No agents yet: force creation flow
                agent_info = await create_agent_interactively()
            else:
                # One or more agents: let the user select or create new
                option_ids = [a.agent_id for a in agents]
                options = option_ids + [create_label]
                prompt = (
                    "Select an agent workspace or create a new one:"
                    if len(agents) == 1
                    else "Select an agent workspace (or create a new one):"
                )
                choice = await request_user_input(
                    "select",
                    prompt,
                    options=options,
                )
                choice_str = str(choice)
                if choice_str == create_label:
                    agent_info = await create_agent_interactively()
                else:
                    for a in agents:
                        if a.agent_id == choice_str:
                            agent_info = a
                            break
                    if agent_info is None:
                        # Fallback to first if something went wrong
                        agent_info = agents[0]

        session = workspace_manager.create_single_session(agent_info)
        workspace_config = session.workspace_config

        # Register workspace-scoped tools now that session paths are known
        tool_registry.register(ManagePlanTool(workspace_config))
        tool_registry.register(ManageTodosTool(workspace_config))
        tool_registry.register(ReadSoulTool(workspace_config))

        emitter.emit(
            {
                "type": "boot_complete",
                "agentId": workspace_config.agent_id,
                "sessionId": workspace_config.session_id,
            }
        )
        emitter.emit(
            {
                "type": "status_update",
                "label": f"Agent {workspace_config.agent_id} ready",
                "status": "done",
            }
        )
        return workspace_manager, workspace_config

    # Bootstrap workspace at startup so the TUI can drive selection/creation
    _, workspace_config = await bootstrap_workspace()
    # Attach workspace configuration to the agent loop up front
    loop.workspace = workspace_config  # type: ignore[attr-defined]

    state: AgentState | None = None

    # Main command loop
    try:
        while True:
            queued_at, cmd = await command_queue.get()
            emit_perf(
                "perf_bridge_queue_wait",
                queue="command",
                wait_ms=round((time.monotonic() - queued_at) * 1000.0, 3),
                depth=command_queue.qsize(),
            )
            if cmd is None:
                break
            msg_type = cmd.get("type")

            if msg_type == "switch_agent":
                # Reset state and re-run interactive selection/creation flow
                state = None
                emitter.emit(
                    {
                        "type": "status_update",
                        "label": "Switching agent...",
                        "status": "running",
                    }
                )
                _, workspace_config = await bootstrap_workspace(force_interactive=True)
                loop.workspace = workspace_config  # type: ignore[attr-defined]
                emitter.emit(
                    {
                        "type": "status_update",
                        "label": "Agent switch complete",
                        "status": "done",
                    }
                )
                continue

            if msg_type == "manage_mcps":
                emitter.emit(
                    {
                        "type": "status_update",
                        "label": "Updating MCP settings...",
                        "status": "running",
                    }
                )
                await manage_mcps_interactively()
                emitter.emit(
                    {
                        "type": "status_update",
                        "label": "MCP settings updated",
                        "status": "done",
                    }
                )
                continue

            if msg_type == "refresh_mcps":
                await refresh_mcp_tools()
                continue

            if msg_type == "start":
                task = cmd.get("task") or ""
                if not task:
                    continue

                # Re-evaluate MCP toggles before each task so current-session
                # enable/disable changes take effect immediately.
                await refresh_mcp_tools()

                logger.info("starting_agent", task=task[:100])
                emitter.emit(
                    {
                        "type": "status_update",
                        "label": "Running...",
                        "status": "running",
                    }
                )

                prov = (cmd.get("provider") or provider).lower()
                if prov != provider and state is None:
                    try:
                        llm_client = create_llm_client(provider=prov)
                        loop.llm_client = llm_client
                        loop.planner = type(loop.planner)(llm_client)
                    except ValueError:
                        pass
                turns = cmd.get("maxTurns") or cmd.get("max_turns") or max_turns
                loop.max_turns = turns

                state_before_run = state.model_copy(deep=True) if state is not None else None

                async def run_agent() -> AgentState:
                    if state is None:
                        return await loop.run(task)
                    return await loop.run_continue(state, task)

                agent_task = asyncio.create_task(run_agent())
                next_cmd_task = asyncio.create_task(command_queue.get())

                done, pending = await asyncio.wait(
                    [agent_task, next_cmd_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if agent_task in done:
                    next_cmd_task.cancel()
                    try:
                        await next_cmd_task
                    except asyncio.CancelledError:
                        pass
                    try:
                        state = agent_task.result()
                    except Exception as e:
                        logger.exception("bridge_run_error")
                        emitter.emit(
                            {"type": "text_stream", "content": f"[Error: {e!s}]"}
                        )
                    emitter.emit(
                        {"type": "status_update", "label": "Done", "status": "done"}
                    )
                else:
                    _, cmd = next_cmd_task.result()
                    logger.info("request_aborted", task=task[:100])
                    agent_task.cancel()
                    try:
                        await agent_task
                    except asyncio.CancelledError:
                        pass
                    if state_before_run is not None:
                        state = state_before_run
                    emitter.emit(
                        {
                            "type": "status_update",
                            "label": "Aborted",
                            "status": "done",
                        }
                    )
                    if cmd is not None and cmd.get("type") != "abort":
                        main_loop.call_soon_threadsafe(command_queue.put_nowait, (time.monotonic(), cmd))
    except asyncio.CancelledError:
        pass
    finally:
        emitter.close()
        for adapter in mcp_adapters:
            try:
                await adapter.close()
            except Exception as e:
                logger.warning("mcp_close_error", error=str(e))


def main() -> None:
    """Entry point for proxi-bridge.

    .. deprecated::
        The bridge is superseded by the gateway HTTP/SSE transport.
        Use ``proxi-gateway`` instead.  This entry point remains for
        backward compatibility during the transition period.
    """
    import argparse
    import warnings

    warnings.warn(
        "proxi-bridge is deprecated. The TUI now connects to the gateway over SSE. "
        "Use `proxi-gateway` or `proxi-gateway-ctl start` instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    parser = argparse.ArgumentParser(
        description="Proxi bridge for TUI clients (DEPRECATED — use gateway)")
    parser.add_argument(
        "--agent-id",
        type=str,
        help="Agent workspace ID to use (otherwise TUI will drive selection/creation)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_bridge(agent_id=args.agent_id))
    except KeyboardInterrupt:
        sys.exit(130)
