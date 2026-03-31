"""search_tools — on-demand deferred tool discovery.

Returns full tool schemas into the message window so the LLM can read the
parameter contracts and invoke the tools via ``call_tool``.  Deferred tools
are never promoted into the live tools array, keeping the prompt-cache prefix
stable for the entire session.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from proxi.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from proxi.tools.registry import ToolRegistry


class SearchToolsTool(BaseTool):
    """Discover deferred tools by keyword query.

    The LLM calls this when it needs a capability not in its current tool list.
    Matching tool schemas are injected into the message window so the LLM can
    read the parameter contracts.  Use ``call_tool`` to execute any returned
    tool.

    Deferred tools are **never** promoted to the live tool list; the tools
    array stays frozen so the prompt-cache prefix is never invalidated.

    This tool is always registered as *live* (never deferred).
    """

    def __init__(self, registry: "ToolRegistry", top_k: int = 5) -> None:
        super().__init__(
            name="search_tools",
            description=(
                "Discover additional tools by keyword. "
                "Returns full schemas for matched tools — read the schema then use "
                "call_tool(tool_name, args) to execute. "
                "MUST be called before attempting any action whose tool is not in your current list. "
                "Never assume a tool exists or hallucinate an action — always search first."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Short phrase describing the action you need to perform. "
                            "Examples: 'send email', 'create calendar event', 'write obsidian note'."
                        ),
                    },
                },
                "required": ["query"],
            },
            parallel_safe=False,
        )
        self._registry = registry
        self._top_k = top_k

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "").strip()
        if not query:
            return ToolResult(
                success=False,
                output="",
                error="query parameter is required",
            )

        new_specs = self._registry.search_deferred(query, top_k=self._top_k)

        if not new_specs:
            if not self._registry.has_deferred_tools():
                return ToolResult(
                    success=True,
                    output="No additional tools are available.",
                )
            if self._registry._schema_injected:
                return ToolResult(
                    success=True,
                    output=(
                        f"No new tools matched '{query}'. "
                        "Previously discovered tools are still callable via call_tool."
                    ),
                )
            return ToolResult(
                success=True,
                output=f"No tools matched '{query}'. Try different keywords.",
            )

        lines: list[str] = [
            "NEXT STEP: call call_tool(tool_name, args) — do NOT call any other tool first.",
            "",
        ]
        for spec in new_specs:
            lines.append(f"tool_name: {spec.name}")
            lines.append(f"  description: {spec.description}")
            props = spec.parameters.get("properties", {}) if isinstance(spec.parameters, dict) else {}
            required = set(spec.parameters.get("required", [])) if isinstance(spec.parameters, dict) else set()
            if props:
                for pname, pdef in props.items():
                    ptype = pdef.get("type", "any") if isinstance(pdef, dict) else "any"
                    req = " (required)" if pname in required else " (optional)"
                    lines.append(f"  arg {pname}: {ptype}{req}")
            lines.append("")
        return ToolResult(success=True, output="\n".join(lines).strip())
