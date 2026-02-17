"""
Headless bridge for the proxi agent: JSON-RPC over stdin/stdout for TUI clients.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from proxi.cli.main import create_llm_client, setup_mcp, setup_sub_agents, setup_tools
from proxi.tools.workspace_tools import ManageTodosTool, ReadSoulTool, UpdatePlanTool
from proxi.core.loop import AgentLoop
from proxi.core.state import AgentState
from proxi.observability.logging import get_logger, init_log_manager
from proxi.workspace import WorkspaceManager

logger = get_logger(__name__)


class StdioEmitter:
    """Emits bridge messages as JSON lines to stdout."""

    def __init__(self) -> None:
        self._closed = False

    def emit(self, msg: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            line = json.dumps(msg) + "\n"
            sys.stdout.write(line)
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            self._closed = True


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
    if no_sub_agents:
        sub_agent_manager = None
    else:
        logger.info("setting_up_sub_agents")
        sub_agent_manager = setup_sub_agents(llm_client)

    emitter = StdioEmitter()

    # Workspace manager for global/agent/session layout
    workspace_manager = WorkspaceManager()
    workspace_manager.ensure_global_system_prompt()

    # Create initial agent loop (workspace will be attached after bootstrap)
    loop = AgentLoop(
        llm_client=llm_client,
        tool_registry=tool_registry,
        sub_agent_manager=sub_agent_manager,
        max_turns=max_turns,
        enable_reflection=True,
        emitter=emitter,
        workspace=None,
    )

    # Tell TUI we are ready to accept commands (before slow MCP setup)
    emitter.emit({"type": "ready"})

    mcp_adapter = None
    if mcp_server:
        try:
            mcp_adapter = await asyncio.wait_for(setup_mcp(mcp_server), timeout=10.0)
            if mcp_adapter:
                for tool in await mcp_adapter.get_tools():
                    tool_registry.register(tool)
        except asyncio.TimeoutError:
            logger.warning("mcp_setup_timeout", server=mcp_server)
        except Exception as e:
            logger.warning("mcp_setup_error", error=str(e))

    # Separate queues for command messages and user_input responses
    command_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    user_input_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
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
                        user_input_queue.put_nowait, obj)
                else:
                    main_loop.call_soon_threadsafe(
                        command_queue.put_nowait, obj)
            except json.JSONDecodeError:
                continue
        main_loop.call_soon_threadsafe(command_queue.put_nowait, None)
        main_loop.call_soon_threadsafe(user_input_queue.put_nowait, None)

    async def run_reader() -> None:
        await asyncio.to_thread(stdin_reader)

    asyncio.create_task(run_reader())

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
            cmd = await user_input_queue.get()
            if cmd is None:
                raise asyncio.CancelledError("Input stream closed")
            if cmd.get("type") == "user_input":
                return cmd.get("value")

    async def bootstrap_workspace() -> tuple[WorkspaceManager, Any]:
        """Select or create an agent and single-session workspace."""
        # Discover existing agents
        agents = workspace_manager.list_agents()
        agent_info = None

        if agent_id:
            # Non-interactive: prefer explicit agent_id
            for a in agents:
                if a.agent_id == agent_id:
                    agent_info = a
                    break
            if agent_info is None:
                agent_info = workspace_manager.create_agent(
                    name=agent_id,
                    persona="General-purpose TUI agent.",
                    mission="Assist the user with interactive tasks.",
                    agent_id=agent_id,
                )
        else:
            if not agents:
                # Creation flow: ask for identity details
                name = await request_user_input("text", "Enter a name for this agent:")
                persona = await request_user_input(
                    "text",
                    "Briefly describe this agent's persona/voice:",
                )
                mission = await request_user_input(
                    "text",
                    "What is this agent's primary mission?",
                )
                agent_info = workspace_manager.create_agent(
                    name=str(name or "Proxi"),
                    persona=str(persona or "Helpful, patient, and clear."),
                    mission=str(
                        mission or "Assist the user with their tasks."),
                )
            elif len(agents) == 1:
                agent_info = agents[0]
            else:
                # Multiple agents: let the user select by agent_id
                options = [a.agent_id for a in agents]
                choice = await request_user_input(
                    "select",
                    "Select an agent workspace:",
                    options=options,
                )
                choice_str = str(choice)
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
        tool_registry.register(UpdatePlanTool(workspace_config))
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

    state: AgentState | None = None
    workspace_config: Any | None = None

    # Main command loop
    try:
        while True:
            cmd = await command_queue.get()
            if cmd is None:
                break
            msg_type = cmd.get("type")
            if msg_type == "start":
                task = cmd.get("task") or ""
                if not task:
                    continue

                # Ensure workspace is bootstrapped before the first task
                if workspace_config is None:
                    _, workspace_config = await bootstrap_workspace()

                logger.info("starting_agent", task=task[:100])
                emitter.emit(
                    {
                        "type": "status_update",
                        "label": "Running...",
                        "status": "running",
                    }
                )
                try:
                    prov = (cmd.get("provider") or provider).lower()
                    if prov != provider and state is None:
                        try:
                            llm_client = create_llm_client(provider=prov)
                            # Swap client on existing loop and rebuild planner
                            loop.llm_client = llm_client
                            loop.planner = type(loop.planner)(llm_client)
                        except ValueError:
                            pass
                    turns = cmd.get("maxTurns") or cmd.get(
                        "max_turns") or max_turns
                    loop.max_turns = turns

                    if state is None:
                        # Attach workspace to initial state
                        # type: ignore[attr-defined]
                        loop.workspace = workspace_config
                        state = await loop.run(task)
                    else:
                        state = await loop.run_continue(state, task)
                except Exception as e:
                    logger.exception("bridge_run_error")
                    emitter.emit(
                        {"type": "text_stream", "content": f"[Error: {e!s}]"}
                    )
                emitter.emit(
                    {
                        "type": "status_update",
                        "label": "Done",
                        "status": "done",
                    }
                )
    except asyncio.CancelledError:
        pass
    finally:
        emitter._closed = True
        if mcp_adapter:
            await mcp_adapter.close()


def main() -> None:
    """Entry point for proxi-bridge."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Proxi bridge for TUI clients")
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
