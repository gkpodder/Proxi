"""MCP adapters to convert MCP tools/resources to proxi tools."""

from typing import Any

from proxi.mcp.client import MCPClient
from proxi.tools.base import BaseTool, ToolResult
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class MCPToolAdapter(BaseTool):
    """Adapter that wraps an MCP tool as a proxi tool."""

    def __init__(self, mcp_client: MCPClient, tool_spec: dict[str, Any]):
        """
        Initialize MCP tool adapter.

        Args:
            mcp_client: MCP client instance
            tool_spec: Tool specification from MCP server
        """
        name = tool_spec.get("name", "unknown")
        description = tool_spec.get("description", "")
        parameters = tool_spec.get("inputSchema", {})

        super().__init__(
            name=f"mcp_{name}",
            description=f"[MCP] {description}",
            parameters_schema=parameters,
        )
        self.mcp_client = mcp_client
        self.mcp_tool_name = name
        self.logger = logger

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the MCP tool."""
        try:
            result = await self.mcp_client.call_tool(self.mcp_tool_name, arguments)

            if "error" in result:
                return ToolResult(
                    success=False,
                    output="",
                    error=result["error"],
                )

            # Extract content from MCP response
            content = result.get("content", [])
            if isinstance(content, list) and content:
                # MCP returns content as list of objects with "text" or "type"
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if "text" in item:
                            text_parts.append(item["text"])
                        elif "type" in item and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                output = "\n".join(text_parts) if text_parts else str(content)
            else:
                output = str(content) if content else "Tool executed successfully"

            return ToolResult(
                success=True,
                output=output,
                metadata={"mcp_tool": self.mcp_tool_name},
            )

        except Exception as e:
            self.logger.error("mcp_tool_error", tool=self.mcp_tool_name, error=str(e))
            return ToolResult(
                success=False,
                output="",
                error=f"MCP tool error: {str(e)}",
            )


class MCPAdapter:
    """Adapter for integrating MCP servers into proxi."""

    def __init__(self, mcp_client: MCPClient):
        """Initialize MCP adapter."""
        self.mcp_client = mcp_client
        self.logger = logger

    async def initialize(self) -> None:
        """Initialize the MCP connection."""
        await self.mcp_client.initialize()

    async def get_tools(self) -> list[MCPToolAdapter]:
        """Get all tools from MCP server as proxi tools."""
        tools = []
        try:
            mcp_tools = await self.mcp_client.list_tools()
            for tool_spec in mcp_tools:
                adapter = MCPToolAdapter(self.mcp_client, tool_spec)
                tools.append(adapter)
            self.logger.info("mcp_tools_loaded", count=len(tools))
        except Exception as e:
            self.logger.error("mcp_tools_error", error=str(e))
        return tools

    async def close(self) -> None:
        """Close the MCP connection."""
        await self.mcp_client.close()
