"""
Headless bridge for the proxi agent: JSON-RPC over stdin/stdout for TUI clients.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from proxi.agents.registry import SubAgentManager, SubAgentRegistry
from proxi.agents.summarizer import SummarizerAgent
from proxi.cli.main import (
    create_llm_client,
    setup_mcp,
    setup_sub_agents,
    setup_tools,
)
from proxi.core.loop import AgentLoop
from proxi.core.state import AgentState
from proxi.observability.logging import setup_logging, get_logger

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


async def run_bridge() -> None:
    """Run the bridge: read JSON commands from stdin, run agent, emit to stdout."""
    # When piped (e.g. by TUI), use line buffering so we see input/output immediately
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if not sys.stdin.isatty() and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(line_buffering=True)

    working_dir = Path(os.environ.get("PROXI_WORKING_DIR", ".")).resolve()
    log_dir = working_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "proxi.log"
    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"), log_file=log_file)
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
    loop = AgentLoop(
        llm_client=llm_client,
        tool_registry=tool_registry,
        sub_agent_manager=sub_agent_manager,
        max_turns=max_turns,
        enable_reflection=True,
        emitter=emitter,
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

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def stdin_reader() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                main_loop.call_soon_threadsafe(queue.put_nowait, obj)
            except json.JSONDecodeError:
                pass
        main_loop.call_soon_threadsafe(queue.put_nowait, None)

    async def run_reader() -> None:
        await asyncio.to_thread(stdin_reader)

    asyncio.create_task(run_reader())

    state: AgentState | None = None

    try:
        while True:
            cmd = await queue.get()
            if cmd is None:
                break
            msg_type = cmd.get("type")
            if msg_type == "start":
                task = cmd.get("task") or ""
                if not task:
                    continue
                logger.info("starting_agent", task=task[:100])
                emitter.emit({"type": "status_update",
                             "label": "Running...", "status": "running"})
                try:
                    prov = (cmd.get("provider") or provider).lower()
                    if prov != provider and state is None:
                        try:
                            llm_client = create_llm_client(provider=prov)
                            loop.llm_client = llm_client
                            loop.planner = type(loop.planner)(llm_client)
                        except ValueError:
                            pass
                    turns = cmd.get("maxTurns") or cmd.get(
                        "max_turns") or max_turns
                    loop.max_turns = turns
                    if state is None:
                        state = await loop.run(task)
                    else:
                        state = await loop.run_continue(state, task)
                except Exception as e:
                    logger.exception("bridge_run_error")
                    emitter.emit(
                        {"type": "text_stream", "content": f"[Error: {e!s}]"})
                emitter.emit({"type": "status_update",
                             "label": "Done", "status": "done"})
            elif msg_type == "user_input":
                # Reserved for future HITL: pass value to a waiting handler
                pass
    except asyncio.CancelledError:
        pass
    finally:
        emitter._closed = True
        if mcp_adapter:
            await mcp_adapter.close()


def main() -> None:
    """Entry point for proxi-bridge."""
    try:
        asyncio.run(run_bridge())
    except KeyboardInterrupt:
        sys.exit(130)
