"""Tool registry for managing available tools."""

from collections.abc import Sequence
from typing import Any

from proxi.llm.schemas import ToolSpec
from proxi.tools.base import Tool, ToolResult


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self):
        """Initialize the registry."""
        self._tools: dict[str, Tool] = {}
        self._raw_specs: list[ToolSpec] = []

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def register_raw_spec(self, spec: ToolSpec) -> None:
        """Register a raw tool spec (e.g. for tools that are intercepted, not executed)."""
        self._raw_specs.append(spec)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> Sequence[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def to_specs(self) -> list[ToolSpec]:
        """Convert all tools to specifications."""
        tool_specs = [ToolSpec(**tool.to_spec()) for tool in self._tools.values()]
        return tool_specs + self._raw_specs

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool."""
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{name}' not found",
            )
        return await tool.execute(arguments)
