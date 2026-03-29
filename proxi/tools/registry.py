"""Tool registry for managing available tools."""

from collections.abc import Sequence
from typing import Any

from proxi.llm.schemas import ToolSpec
from proxi.tools.base import Tool, ToolResult
from proxi.tools.search import BM25SearchStrategy, ToolSearchEntry, ToolSearchStrategy, build_index
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """Registry for managing tools.

    Tools exist in one of two tiers:

    * **Live** (``_tools``): included in ``to_specs()`` and sent to the LLM
      on every call.
    * **Deferred** (``_deferred_tools``): hidden from the LLM until the LLM
      calls ``search_tools``, which promotes matching tools to the live tier.
    """

    def __init__(self, search_strategy: ToolSearchStrategy | None = None):
        """Initialize the registry."""
        self._tools: dict[str, Tool] = {}
        self._raw_specs: list[ToolSpec] = []
        self._deferred_tools: dict[str, Tool] = {}
        self._deferred_index: list[ToolSearchEntry] = []
        self._search_strategy: ToolSearchStrategy = search_strategy or BM25SearchStrategy()

    def register(self, tool: Tool) -> None:
        """Register a tool in the live tier."""
        self._tools[tool.name] = tool

    def register_deferred(self, tool: Tool) -> None:
        """Register a tool in the deferred (hidden) tier.

        Deferred tools are indexed for search but not included in ``to_specs()``
        until ``search_and_load`` promotes them to the live tier.
        """
        self._deferred_tools[tool.name] = tool
        self._rebuild_deferred_index()

    def has_deferred_tools(self) -> bool:
        """Return True if any tools remain in the deferred tier."""
        return bool(self._deferred_tools)

    def deferred_tool_count(self) -> int:
        """Return the number of tools currently in the deferred tier."""
        return len(self._deferred_tools)

    def search_and_load(
        self,
        query: str,
        top_k: int = 5,
        strategy: ToolSearchStrategy | None = None,
    ) -> list[Tool]:
        """Search deferred tools and promote matches to the live tier.

        Args:
            query: Keywords describing the capability needed.
            top_k: Maximum number of tools to load per call.
            strategy: Override the registry's default search strategy.

        Returns:
            List of tools that were newly promoted (empty if none matched or
            no deferred tools remain).
        """
        if not self._deferred_tools:
            return []

        active_strategy = strategy or self._search_strategy
        matched = active_strategy.search(query, self._deferred_index, top_k)

        promoted: list[Tool] = []
        for tool in matched:
            if tool.name in self._deferred_tools:
                self._tools[tool.name] = tool
                del self._deferred_tools[tool.name]
                promoted.append(tool)

        if promoted:
            self._rebuild_deferred_index()
            logger.info(
                "tools_promoted_from_deferred",
                count=len(promoted),
                names=[t.name for t in promoted],
            )

        return promoted

    def unregister_by_prefix(self, prefix: str) -> int:
        """Unregister tools whose names start with the given prefix."""
        to_remove = [name for name in self._tools if name.startswith(prefix)]
        for name in to_remove:
            self._tools.pop(name, None)

        deferred_remove = [name for name in self._deferred_tools if name.startswith(prefix)]
        for name in deferred_remove:
            self._deferred_tools.pop(name, None)
        if deferred_remove:
            self._rebuild_deferred_index()

        return len(to_remove) + len(deferred_remove)

    def _rebuild_deferred_index(self) -> None:
        """Rebuild the search index from the current deferred tool set."""
        self._deferred_index = build_index(list(self._deferred_tools.values()))

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

    def is_parallel_safe(self, name: str) -> bool:
        """Whether a tool is marked safe to execute in parallel."""
        tool = self.get(name)
        return bool(getattr(tool, "parallel_safe", False)) if tool is not None else False

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
