"""search_tools — on-demand deferred tool loader.

Exposes deferred tools to the LLM by searching the deferred registry and
promoting matching tools to the live tier.  The LLM is informed via the
system prompt that additional tools may exist; it calls this tool with a
natural-language query to discover and activate them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from proxi.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from proxi.tools.registry import ToolRegistry


class SearchToolsTool(BaseTool):
    """Search for and load deferred tools by keyword query.

    The LLM calls this when it needs a capability not available in its
    current tool list.  Matching tools are permanently added to the live
    registry for the remainder of the session.

    This tool is always registered as *live* (never deferred) so the LLM
    can always reach it.
    """

    def __init__(self, registry: "ToolRegistry", top_k: int = 5) -> None:
        super().__init__(
            name="search_tools",
            description=(
                "Load additional tools on demand. "
                "MUST be called before attempting any action whose specific tool is not in your current tool list. "
                "For example: to send an email call search_tools('send email') first — do NOT use read_emails to send. "
                "After calling this, the matched tools become available immediately; proceed with the task using them. "
                "Never assume a tool exists or hallucinate an action — always search first."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Short phrase describing the action you need to perform. "
                            "Examples: 'send email', 'create calendar event', 'write obsidian note', 'notion page'."
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

        newly_loaded = self._registry.search_and_load(query, top_k=self._top_k)

        if not newly_loaded:
            if not self._registry.has_deferred_tools():
                return ToolResult(
                    success=True,
                    output="No additional tools are available to load.",
                )
            return ToolResult(
                success=True,
                output=f"No tools matched '{query}'. Try different keywords.",
            )

        lines = [f"Loaded {len(newly_loaded)} tool(s). These are now active — use them to complete the task:"]
        for tool in newly_loaded:
            lines.append(f"- {tool.name}: {tool.description}")
        return ToolResult(success=True, output="\n".join(lines))
