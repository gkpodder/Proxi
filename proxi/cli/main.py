"""CLI entry point for proxi."""

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from proxi.agents.registry import SubAgentManager, SubAgentRegistry
from proxi.agents.summarizer import SummarizerAgent
from proxi.core.loop import AgentLoop
from proxi.llm.anthropic import AnthropicClient
from proxi.llm.openai import OpenAIClient
from proxi.llm.vllm import VLLMClient
from proxi.mcp.adapters import MCPAdapter
from proxi.mcp.client import MCPClient
from proxi.observability.logging import get_logger, init_log_manager
from proxi.security.key_store import get_key_value
from proxi.tools.coding import register_coding_tools
from proxi.tools.filesystem import ReadFileTool, WriteFileTool
from proxi.tools.registry import ToolRegistry
from proxi.tools.shell import ExecuteCodeTool as ExecuteCommandTool  # noqa: F401  (compat alias)
from proxi.tools.workspace_tools import ManagePlanTool, ManageTodosTool, ReadSoulTool
from proxi.workspace import WorkspaceManager

logger = get_logger(__name__)


DEFAULT_INTEGRATIONS_CONFIG: dict[str, Any] = {
    "integrations": {
        "gmail": {"type": "cli", "defer_loading": True, "always_load": ["read_emails"]},
        "google_calendar": {"type": "cli", "defer_loading": True, "always_load": ["calendar_list_events"]},
        "spotify": {"type": "cli", "defer_loading": True, "always_load": []},
        "notion": {"type": "cli", "defer_loading": True, "always_load": []},
        "obsidian": {"type": "cli", "defer_loading": True, "always_load": []},
        "weather": {"type": "cli", "defer_loading": False, "always_load": ["get_weather"]},
    },
}


def create_llm_client(
    provider: str = "openai",
    model: str | None = None,
) -> OpenAIClient | AnthropicClient | VLLMClient:
    """Create an LLM client based on provider."""
    if provider.lower() == "anthropic":
        api_key = get_key_value("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in SQLite key store. Use the React frontend (🔐 button) to add it.")
        return AnthropicClient(
            api_key=api_key,
            model=(model or "claude-3-5-sonnet-20241022"),
        )
    elif provider.lower() == "vllm":
        base_url = get_key_value("VLLM_BASE_URL") or "http://localhost:8000/v1"
        api_key = get_key_value("VLLM_API_KEY")  # optional — vLLM may run without auth
        return VLLMClient(
            api_key=api_key or None,
            base_url=base_url,
            model=(model or "local"),
        )
    else:
        api_key = get_key_value("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in SQLite key store. Use the React frontend (🔐 button) to add it.")
        return OpenAIClient(
            api_key=api_key,
            model=(model or "gpt-5-mini-2025-08-07"),
        )


def setup_tools(working_directory: Path | None = None) -> ToolRegistry:
    """Set up the tool registry with default tools."""
    from proxi.browser.tools import register_browser_tools
    from proxi.tools.path_guard import PathGuard

    registry = ToolRegistry()
    guard = PathGuard(working_directory)

    builtin_tools = [
        ReadFileTool(guard=guard),
        WriteFileTool(guard=guard),
        # Shell tool is not registered by default (security)
        # ExecuteCommandTool(working_directory=working_directory),
    ]
    for tool in builtin_tools:
        if getattr(tool, "defer_loading", False):
            registry.register_deferred(tool)
        else:
            registry.register(tool)

    register_browser_tools(registry)

    return registry


def setup_sub_agents(llm_client: OpenAIClient | AnthropicClient | VLLMClient) -> SubAgentManager:
    """Set up the sub-agent registry and manager."""
    from proxi.browser.agent import BrowserSubAgent

    registry = SubAgentRegistry()

    # Register summarizer agent
    summarizer = SummarizerAgent(llm_client)
    registry.register(summarizer)

    # Register browser agent
    browser_agent = BrowserSubAgent()
    registry.register(browser_agent)

    manager = SubAgentManager(registry)
    return manager


def build_cli_tool_lists(
    *,
    config: dict[str, Any] | None = None,
    enabled_integration_names: set[str] | None = None,
    db_path: str | Path | None = None,
) -> tuple[list[Any], list[Any]]:
    """Build live and deferred CLI tool instances from integrations.json + key store.

    Integration-backed tools are omitted when the integration is disabled in the key
    store, missing from config, or not of type ``cli``. Core tools (no
    ``integration_name``) follow each class's ``defer_loading`` flag.
    """
    from proxi.security.key_store import get_enabled_integrations
    from proxi.tools.cli_tool import CLI_TOOLS

    if config is None:
        config = load_integrations_config()
    integrations = config.get("integrations", {})
    if enabled_integration_names is None:
        enabled_integration_names = set(get_enabled_integrations(db_path))

    live: list[Any] = []
    deferred: list[Any] = []

    for tool_class in CLI_TOOLS:
        tool = tool_class()  # type: ignore[call-arg]
        integration_name = getattr(tool_class, "integration_name", None)

        if integration_name is None:
            if tool.defer_loading:
                deferred.append(tool)
                logger.info("cli_tool_deferred", tool=tool.name)
            else:
                live.append(tool)
                logger.info("cli_tool_registered", tool=tool.name)
            continue

        if integration_name not in integrations:
            logger.info(
                "cli_tool_skipped_no_config",
                tool=tool.name,
                integration=integration_name,
            )
            continue

        if integration_name not in enabled_integration_names:
            logger.info(
                "cli_tool_skipped_disabled",
                tool=tool.name,
                integration=integration_name,
            )
            continue

        int_cfg = integrations[integration_name]
        if int_cfg.get("type", "cli") != "cli":
            logger.info(
                "cli_tool_skipped_wrong_type",
                tool=tool.name,
                integration=integration_name,
            )
            continue

        defer = bool(int_cfg.get("defer_loading", True))
        int_always = set(int_cfg.get("always_load", []))
        if not defer or tool.name in int_always:
            live.append(tool)
            logger.info("cli_tool_registered", tool=tool.name)
        else:
            deferred.append(tool)
            logger.info("cli_tool_deferred", tool=tool.name)

    return live, deferred


def auto_load_cli_tools(
    tool_registry: ToolRegistry, db_path: str | Path | None = None
) -> None:
    """Load CLI tools from config/integrations.json into the tool registry."""
    live, deferred = build_cli_tool_lists(db_path=db_path)
    for tool in live:
        tool_registry.register(tool)
    for tool in deferred:
        tool_registry.register_deferred(tool)


async def auto_load_mcp_servers(tool_registry: ToolRegistry) -> list[MCPAdapter]:
    """Auto-load MCP-type integrations from config/integrations.json.

    Returns list of loaded adapters for cleanup.
    """
    from proxi.security.key_store import get_enabled_integrations

    config = load_integrations_config()
    integrations = config.get("integrations", {})
    enabled_names = get_enabled_integrations()
    loaded_adapters = []

    for integration_name, entry in integrations.items():
        if entry.get("type") != "mcp":
            continue
        if integration_name not in enabled_names:
            logger.info("mcp_integration_skipped_not_enabled", integration=integration_name)
            continue

        command = entry.get("command")
        args = entry.get("args", [])
        defer_server = bool(entry.get("defer_loading", False))
        always_load: set[str] = set(entry.get("always_load", []))

        if not command:
            logger.error("mcp_integration_invalid_config", integration=integration_name)
            continue

        try:
            logger.info("auto_loading_mcp_integration", integration=integration_name)
            full_command = [command] + args
            mcp_client = MCPClient(server_command=full_command)
            adapter = MCPAdapter(mcp_client)
            await adapter.initialize()
            mcp_tools = await adapter.get_tools()
            for tool in mcp_tools:
                unprefixed = getattr(tool, "mcp_tool_name", tool.name)
                if defer_server and unprefixed not in always_load:
                    tool_registry.register_deferred(tool)
                    logger.info("mcp_tool_deferred", integration=integration_name, tool=tool.name)
                else:
                    tool_registry.register(tool)
                    logger.info("mcp_tool_registered", integration=integration_name, tool=tool.name)
            loaded_adapters.append(adapter)
        except Exception as e:
            logger.warning("auto_load_mcp_integration_error", integration=integration_name, error=str(e))

    return loaded_adapters


def load_integrations_config() -> dict[str, Any]:
    """Load integration configuration from config/integrations.json.

    Falls back to a built-in default when the file is absent, so auto-load
    behavior remains stable without requiring a repo-level config file.
    """
    config_path = Path("config/integrations.json")
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("integrations_config_load_error", error=str(e))
    logger.info("integrations_config_missing_using_defaults", path=str(config_path))
    return deepcopy(DEFAULT_INTEGRATIONS_CONFIG)


async def setup_mcp(mcp_server: str | None = None) -> MCPAdapter | None:
    """Set up an ad-hoc MCP adapter from a server command string."""
    if not mcp_server:
        return None

    # Parse MCP server command
    # Format: "command:arg1:arg2" or just "command"
    # Also support space-separated: "command arg1 arg2"
    if " " in mcp_server and ":" not in mcp_server:
        # Space-separated format
        import shlex
        command = shlex.split(mcp_server)
    else:
        # Colon-separated format
        parts = mcp_server.split(":")
        command = [parts[0]]
        if len(parts) > 1:
            command.extend(parts[1:])

    mcp_client = MCPClient(server_command=command)
    adapter = MCPAdapter(mcp_client)

    try:
        await adapter.initialize()
        return adapter
    except Exception as e:
        logger.error("mcp_setup_error", error=str(e), exc_info=True)
        return None


async def main():
    """Main CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Proxi - A general-purpose agent")
    parser.add_argument(
        "task",
        nargs="?",
        help="Task description for the agent",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "anthropic"],
        default="openai",
        help="LLM provider to use",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Maximum number of turns",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--working-directory",
        type=str,
        help="Working directory for file operations",
    )
    parser.add_argument(
        "--no-reflection",
        action="store_true",
        help="Disable reflection",
    )
    parser.add_argument(
        "--mcp-server",
        type=str,
        help="MCP server command (e.g., 'npx:@modelcontextprotocol/server-filesystem /path'). Use 'filesystem:/path' for filesystem server shortcut.",
    )
    parser.add_argument(
        "--mcp-filesystem",
        type=str,
        metavar="PATH",
        help="Use the filesystem MCP server with the given path (requires Node.js/npx). Example: --mcp-filesystem /path/to/dir",
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Disable auto-loading of configured MCP servers",
    )
    parser.add_argument(
        "--no-sub-agents",
        action="store_true",
        help="Disable sub-agents",
    )
    parser.add_argument(
        "--agent-id",
        type=str,
        help="Agent workspace ID to use (defaults to 'default' if not present)",
    )

    args = parser.parse_args()

    # Set up logging with timestamped directory
    log_manager = init_log_manager(base_dir="logs")
    log_manager.configure_logging(level=args.log_level, use_colors=True)
    logger.info("log_directory", path=str(log_manager.get_session_dir()))

    # Get task
    if args.task:
        task = args.task
    elif not sys.stdin.isatty():
        # Read from stdin
        task = sys.stdin.read().strip()
    else:
        parser.print_help()
        sys.exit(1)

    if not task:
        logger.error("No task provided")
        sys.exit(1)

    # Set up working directory
    working_dir = Path(
        args.working_directory) if args.working_directory else Path.cwd()

    mcp_adapters: list[MCPAdapter] = []
    try:
        # Create LLM client
        logger.info("initializing_llm", provider=args.provider)
        llm_client = create_llm_client(provider=args.provider)

        # Set up tools
        logger.info("setting_up_tools")
        tool_registry = setup_tools(working_directory=working_dir)

        # Workspace setup (non-interactive CLI: explicit agent-id or infer)
        workspace_manager = WorkspaceManager()
        workspace_manager.ensure_global_system_prompt()

        agents = workspace_manager.list_agents()

        if args.agent_id:
            agent_id = args.agent_id
            existing = {a.agent_id: a for a in agents}
            if agent_id in existing:
                agent_info = existing[agent_id]
            else:
                agent_info = workspace_manager.create_agent(
                    name=agent_id,
                    persona="General-purpose CLI agent.",
                    agent_id=agent_id,
                )
        else:
            if not agents:
                agent_info = workspace_manager.create_agent(
                    name="default",
                    persona="General-purpose CLI agent.",
                    agent_id="default",
                )
            elif len(agents) == 1:
                agent_info = agents[0]
            else:
                # Multiple agents but no --agent-id; require explicit selection
                names = ", ".join(sorted(a.agent_id for a in agents))
                logger.error(
                    "multiple_agents_found",
                    message=(
                        "Multiple agents exist; please specify one "
                        "with --agent-id. Available agents: %s" % names
                    ),
                )
                print(
                    f"Multiple agents found: {names}. Please re-run with --agent-id <name>.",
                    file=sys.stderr,
                )
                sys.exit(1)

        session = workspace_manager.create_single_session(agent_info)
        workspace_config = session.workspace_config

        # Register workspace-scoped tools now that paths are known
        tool_registry.register(ManagePlanTool(workspace_config))
        tool_registry.register(ManageTodosTool(workspace_config))
        tool_registry.register(ReadSoulTool(workspace_config))

        # Register coding tools based on per-agent config
        agent_config = workspace_manager.read_agent_config(agent_info.agent_id)
        coding_tier = agent_config.get("tool_sets", {}).get("coding", "live")
        register_coding_tools(tool_registry, working_dir=working_dir, tier=str(coding_tier))

        # Register CLI tools from config
        auto_load_cli_tools(tool_registry)

        # Attach working dir to workspace config so tools and prompts can reference it
        workspace_config.curr_working_dir = str(working_dir)

        # Set up MCP adapters (auto-load MCP-type integrations from integrations config)
        if not args.no_mcp:
            logger.info("auto_loading_mcp_integrations")
            mcp_adapters = await auto_load_mcp_servers(tool_registry)

        # Set up explicit MCP server if specified
        mcp_server_cmd = args.mcp_server
        if args.mcp_filesystem:
            # Shortcut for filesystem MCP server
            # Try to use npx if available, otherwise fall back to test server
            import shutil
            npx_path = shutil.which("npx")
            if npx_path:
                mcp_server_cmd = f"npx:@modelcontextprotocol/server-filesystem:{args.mcp_filesystem}"
            else:
                logger.warning(
                    "npx_not_found", message="npx not found, filesystem MCP server requires Node.js. Install Node.js to use this feature.")
                mcp_server_cmd = None

        if mcp_server_cmd:
            # Handle special shortcuts
            if mcp_server_cmd.startswith("filesystem:"):
                path = mcp_server_cmd.split(":", 1)[1]
                import shutil
                npx_path = shutil.which("npx")
                if npx_path:
                    mcp_server_cmd = f"npx:@modelcontextprotocol/server-filesystem:{path}"
                else:
                    logger.warning(
                        "npx_not_found", message="npx not found, filesystem MCP server requires Node.js")
                    mcp_server_cmd = None

            if mcp_server_cmd:
                logger.info("setting_up_explicit_mcp", server=mcp_server_cmd)
                mcp_adapter = await setup_mcp(mcp_server_cmd)
                if mcp_adapter:
                    mcp_adapters.append(mcp_adapter)
                    mcp_tools = await mcp_adapter.get_tools()
                    for tool in mcp_tools:
                        tool_registry.register(tool)
                        logger.info("mcp_tool_registered", tool=tool.name)

        # Register call_tool if any tools were deferred
        if tool_registry.has_deferred_tools():
            from proxi.tools.call_tool_tool import CallToolTool
            tool_registry.register(CallToolTool(tool_registry))
            logger.info("call_tool_registered", deferred_count=tool_registry.deferred_tool_count())

        # Set up sub-agents
        sub_agent_manager = None
        if not args.no_sub_agents:
            logger.info("setting_up_sub_agents")
            sub_agent_manager = setup_sub_agents(llm_client)

        # Create agent loop
        loop = AgentLoop(
            llm_client=llm_client,
            tool_registry=tool_registry,
            sub_agent_manager=sub_agent_manager,
            max_turns=args.max_turns,
            enable_reflection=not args.no_reflection,
            workspace=workspace_config,
        )

        # Run the agent
        logger.info("starting_agent", task=task[:100])
        state = await loop.run(task)

        # Print final result
        print("\n" + "=" * 80)
        print("AGENT COMPLETED")
        print("=" * 80)
        print(f"Status: {state.status.value}")
        print(f"Turns: {state.current_turn}/{state.max_turns}")
        if state.start_time and state.end_time:
            print(f"Duration: {state.end_time - state.start_time:.2f}s")
        print(f"Total tokens: {state.total_tokens}")

        # Print final message if available
        if state.history:
            last_message = state.history[-1]
            if last_message.role == "assistant":
                print("\nFinal Response:")
                print("-" * 80)
                print(last_message.content)

        # Cleanup all MCP adapters
        for adapter in mcp_adapters:
            await adapter.close()

        sys.exit(0 if state.status.value == "completed" else 1)

    except KeyboardInterrupt:
        logger.info("interrupted_by_user")
        for adapter in mcp_adapters:
            await adapter.close()
        sys.exit(130)
    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        for adapter in mcp_adapters:
            await adapter.close()
        sys.exit(1)


def cli_main():
    """Sync wrapper for CLI entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
