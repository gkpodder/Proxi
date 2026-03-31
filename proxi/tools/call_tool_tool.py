"""call_tool — execute a deferred tool discovered via search_tools.

Deferred tools are never promoted into the live tools array (which would bust
the prompt cache).  After the LLM calls search_tools and receives the full
schema, it uses this tool to actually invoke the discovered capability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from proxi.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from proxi.tools.registry import ToolRegistry


class CallToolTool(BaseTool):
    """Execute a deferred tool by name with the provided arguments.

    The LLM must call ``search_tools`` first to discover the tool's schema,
    then pass the exact ``tool_name`` and the ``args`` dict matching that
    schema here.

    This tool is always registered as *live* (never deferred).
    """

    def __init__(self, registry: "ToolRegistry") -> None:
        super().__init__(
            name="call_tool",
            description=(
                "Execute a tool discovered via search_tools. "
                "Pass the exact tool_name from the search_tools result and the args "
                "the tool's schema requires. "
                "Do NOT guess tool names — only call tools returned by search_tools."
            ),
            parameters_schema={
                "type": "object",
                "required": ["tool_name", "args"],
                "additionalProperties": False,
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Exact tool name as returned by search_tools.",
                    },
                    "args": {
                        "type": "object",
                        "description": "Arguments as defined in the tool's parameters schema.",
                    },
                },
            },
            parallel_safe=False,
        )
        self._registry = registry

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        tool_name = arguments.get("tool_name", "").strip()
        args = arguments.get("args", {})

        if not tool_name:
            return ToolResult(
                success=False,
                output="",
                error="tool_name is required",
            )

        if not isinstance(args, dict):
            return ToolResult(
                success=False,
                output="",
                error="args must be an object",
            )

        return await self._registry.execute_deferred(tool_name, args)
