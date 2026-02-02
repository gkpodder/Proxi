"""MCP Multiplexer for running multiple MCP servers simultaneously."""

import asyncio
from typing import List

from proxi.mcp.adapters import MCPAdapter
from proxi.mcp.client import MCPClient
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class MCPMultiplexer:
    """Multiplexes multiple MCP servers, exposing all tools combined."""

    def __init__(self, mcp_servers: List[str | list]):
        """Initialize multiplexer with list of MCP servers."""
        self.mcp_servers = mcp_servers
        self.adapters: List[MCPAdapter] = []
        self.initialized = False

    async def initialize(self) -> None:
        """Initialize all MCP adapters."""
        for server in self.mcp_servers:
            try:
                if isinstance(server, list):
                    command = server
                elif " " in server and ":" not in server:
                    import shlex
                    command = shlex.split(server)
                else:
                    parts = server.split(":")
                    command = [parts[0]]
                    if len(parts) > 1:
                        command.extend(parts[1:])

                logger.debug("mcp_multiplexer_init_server", command=command)
                mcp_client = MCPClient(server_command=command)
                adapter = MCPAdapter(mcp_client)
                await adapter.initialize()
                self.adapters.append(adapter)
                logger.info("mcp_multiplexer_server_initialized", command=str(command))
            except Exception as e:
                logger.error(
                    "mcp_multiplexer_init_error",
                    server=str(server),
                    error=str(e),
                    exc_info=True
                )

        if self.adapters:
            self.initialized = True
            logger.info("mcp_multiplexer_initialized", count=len(self.adapters))

    async def get_tools(self):
        """Get combined tools from all adapters."""
        if not self.initialized:
            return []

        all_tools = []
        for adapter in self.adapters:
            try:
                tools = await adapter.get_tools()
                all_tools.extend(tools)
            except Exception as e:
                logger.error(
                    "mcp_multiplexer_get_tools_error",
                    adapter=adapter,
                    error=str(e)
                )

        logger.debug("mcp_multiplexer_tools_combined", count=len(all_tools))
        return all_tools

    async def call_tool(self, tool_name: str, tool_input: dict):
        """Call tool from first adapter that has it."""
        if not self.initialized:
            raise RuntimeError("Multiplexer not initialized")

        for adapter in self.adapters:
            try:
                tools = await adapter.get_tools()
                if any(t.name == tool_name for t in tools):
                    logger.debug(
                        "mcp_multiplexer_calling_tool",
                        tool=tool_name,
                        adapter=adapter
                    )
                    return await adapter.call_tool(tool_name, tool_input)
            except Exception as e:
                logger.debug(
                    "mcp_multiplexer_tool_not_found",
                    tool=tool_name,
                    adapter=adapter,
                    error=str(e)
                )

        raise ValueError(f"Tool {tool_name} not found in any MCP server")

    async def close(self) -> None:
        """Close all adapters."""
        for adapter in self.adapters:
            try:
                await adapter.close()
            except Exception as e:
                logger.error(
                    "mcp_multiplexer_close_error",
                    adapter=adapter,
                    error=str(e)
                )
