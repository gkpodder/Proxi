"""CLI entry point for proxi."""

import asyncio
import os
import sys
from pathlib import Path

from proxi.agents.registry import SubAgentManager, SubAgentRegistry
from proxi.agents.summarizer import SummarizerAgent
from proxi.agents.browser import BrowserAgent
from proxi.core.loop import AgentLoop
from proxi.llm.anthropic import AnthropicClient
from proxi.llm.openai import OpenAIClient
from proxi.mcp.adapters import MCPAdapter
from proxi.mcp.client import MCPClient
from proxi.observability.logging import setup_logging, get_logger
from proxi.tools.datetime import DateTimeTool
from proxi.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool
from proxi.tools.registry import ToolRegistry
from proxi.tools.shell import ExecuteCommandTool

logger = get_logger(__name__)


def create_llm_client(provider: str = "openai") -> OpenAIClient | AnthropicClient:
    """Create an LLM client based on provider."""
    if provider.lower() == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        return AnthropicClient(api_key=api_key)
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        return OpenAIClient(api_key=api_key)


def setup_tools(working_directory: Path | None = None) -> ToolRegistry:
    """Set up the tool registry with default tools."""
    registry = ToolRegistry()

    # Filesystem tools
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())

    # Shell tool
    registry.register(ExecuteCommandTool(working_directory=working_directory))

    # Datetime tool
    registry.register(DateTimeTool())

    return registry


def setup_sub_agents(llm_client: OpenAIClient | AnthropicClient) -> SubAgentManager:
    """Set up the sub-agent registry and manager."""
    registry = SubAgentRegistry()

    # Register summarizer agent
    summarizer = SummarizerAgent(llm_client)
    registry.register(summarizer)

    # Register browser agent
    browser_agent = BrowserAgent(
        headless=False,  # Set to False to see the browser window
        max_steps=3,  # Very limited steps - just navigate and observe
        allowed_domains=[],  # Empty = allow all domains
        denied_domains=[],   # Add domains to block if needed
        artifacts_base_dir="./browser_artifacts",
    )
    registry.register(browser_agent)

    manager = SubAgentManager(registry)
    return manager


async def setup_mcp(mcp_server: str | None = None) -> MCPAdapter | None:
    """Set up MCP adapter if MCP server is specified."""
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
        # Load MCP tools into tool registry
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
        "--no-sub-agents",
        action="store_true",
        help="Disable sub-agents",
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(level=args.log_level)

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

    mcp_adapter = None
    try:
        # Create LLM client
        logger.info("initializing_llm", provider=args.provider)
        llm_client = create_llm_client(provider=args.provider)

        # Set up tools
        logger.info("setting_up_tools")
        tool_registry = setup_tools(working_directory=working_dir)

        # Set up MCP if specified
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
                logger.info("setting_up_mcp", server=mcp_server_cmd)
                mcp_adapter = await setup_mcp(mcp_server_cmd)
                if mcp_adapter:
                    mcp_tools = await mcp_adapter.get_tools()
                    for tool in mcp_tools:
                        tool_registry.register(tool)
                        logger.info("mcp_tool_registered", tool=tool.name)

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

        # Cleanup MCP if used
        if mcp_adapter:
            await mcp_adapter.close()

        sys.exit(0 if state.status.value == "completed" else 1)

    except KeyboardInterrupt:
        logger.info("interrupted_by_user")
        if mcp_adapter:
            await mcp_adapter.close()
        sys.exit(130)
    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        if mcp_adapter:
            await mcp_adapter.close()
        sys.exit(1)


def cli_main():
    """Sync wrapper for CLI entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
