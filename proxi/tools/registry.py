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
      on every call.  This set never changes mid-session so the prompt-cache
      prefix stays stable.
    * **Deferred** (``_deferred_tools``): hidden from the LLM.  The LLM
      discovers them by calling ``search_tools``, which returns full schemas
      in the *message window*.  Deferred tools are never promoted to the live
      tier; they are executed via ``call_tool`` / ``execute_deferred``.
    """

    def __init__(self, search_strategy: ToolSearchStrategy | None = None):
        """Initialize the registry."""
        self._tools: dict[str, Tool] = {}
        self._raw_specs: list[ToolSpec] = []
        self._deferred_tools: dict[str, Tool] = {}
        self._deferred_index: list[ToolSearchEntry] = []
        self._search_strategy: ToolSearchStrategy = search_strategy or BM25SearchStrategy()
        # Names whose full schemas have already been injected into the message
        # window this session.  Used to deduplicate search_tools results.
        self._schema_injected: set[str] = set()

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

    def search_deferred(
        self,
        query: str,
        top_k: int = 5,
        strategy: ToolSearchStrategy | None = None,
    ) -> list[ToolSpec]:
        """Search deferred tools and return their full specs for injection into the message window.

        Deferred tools are **never** promoted to the live tier; the tools array
        stays frozen so the prompt-cache prefix remains stable.  The returned
        specs should be included in the ``search_tools`` tool-result message so
        the LLM can read the schemas and later call them via ``call_tool``.

        Already-injected tools are filtered out to avoid duplicating schemas in
        the message window across multiple searches in the same session.

        Args:
            query: Natural-language description of the capability needed.
            top_k: Maximum number of tool specs to return.
            strategy: Override the default BM25 search strategy.

        Returns:
            List of :class:`ToolSpec` objects for newly matched tools (empty if
            nothing new matched or no deferred tools exist).
        """
        if not self._deferred_tools:
            return []

        active_strategy = strategy or self._search_strategy
        matched = active_strategy.search(query, self._deferred_index, top_k)

        new_specs: list[ToolSpec] = []
        for tool in matched:
            if tool.name not in self._schema_injected:
                self._schema_injected.add(tool.name)
                new_specs.append(ToolSpec(**tool.to_spec()))

        if new_specs:
            logger.info(
                "deferred_schemas_injected",
                count=len(new_specs),
                names=[s.name for s in new_specs],
            )

        return new_specs

    def suggest_deferred(self, query: str, top_k: int = 3) -> list[tuple[float, "ToolSpec"]]:
        """Search deferred tools and return (score, ToolSpec) pairs.

        Unlike ``search_deferred``, this never deduplicates or tracks injected
        schemas — it is purely for surfacing suggestions to the LLM so it can
        retry with a correct tool name.  Callers are responsible for applying a
        relevance threshold to avoid returning irrelevant suggestions.
        """
        if not self._deferred_tools or not self._deferred_index:
            return []
        strategy = self._search_strategy
        if not hasattr(strategy, "search_with_scores"):
            # Fallback for strategies that don't expose scores
            tools = strategy.search(query, self._deferred_index, top_k)
            return [(1.0, ToolSpec(**t.to_spec())) for t in tools]
        scored = strategy.search_with_scores(query, self._deferred_index, top_k)  # type: ignore[attr-defined]
        return [(score, ToolSpec(**tool.to_spec())) for score, tool in scored]

    async def execute_deferred(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool from the deferred tier by name.

        This is the execution path for tools discovered via ``search_tools``
        and invoked by the LLM through ``call_tool``.

        Args:
            name: Exact tool name as returned by ``search_deferred``.
            arguments: Argument dict matching the tool's parameters schema.

        Returns:
            :class:`ToolResult` with the execution output, or an error result
            if the tool name is not found in the deferred tier.
        """
        tool = self._deferred_tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Tool '{name}' not found in deferred registry. "
                    "Call search_tools first to discover available tools."
                ),
            )
        return await tool.execute(arguments)

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

        # Clear injected-schema tracking for removed tools so they can be
        # re-discovered cleanly after an MCP reload.
        self._schema_injected -= {*to_remove, *deferred_remove}

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

    def get_deferred_specs(self) -> list[ToolSpec]:
        """Return lightweight specs (name + description only) for all deferred tools.

        Used to populate the system prompt with stubs so the LLM knows which
        services are available on demand, without revealing full schemas.
        Parameters are intentionally omitted — the LLM gets those only after
        calling ``search_tools``.
        """
        return [
            ToolSpec(name=t.name, description=t.description, parameters={})
            for t in self._deferred_tools.values()
        ]

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
