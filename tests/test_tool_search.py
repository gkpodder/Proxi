"""Tests for the tool search / deferred loading feature."""

import pytest

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.registry import ToolRegistry
from proxi.tools.search import BM25SearchStrategy, RegexSearchStrategy, build_index
from proxi.tools.search_tools_tool import SearchToolsTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tool(name: str, description: str, defer: bool = False) -> BaseTool:
    """Create a minimal tool for testing."""

    class _Tool(BaseTool):
        async def execute(self, arguments: dict) -> ToolResult:  # type: ignore[override]
            return ToolResult(success=True, output="ok")

    t = _Tool(
        name=name,
        description=description,
        parameters_schema={"type": "object", "properties": {}},
    )
    t.defer_loading = defer
    return t


# ---------------------------------------------------------------------------
# BM25SearchStrategy
# ---------------------------------------------------------------------------

class TestBM25SearchStrategy:
    def _make_entries(self):
        tools = [
            make_tool("send_email", "Send an email to a recipient"),
            make_tool("read_email", "Read emails from inbox"),
            make_tool("calendar_create", "Create a calendar event or meeting"),
            make_tool("calendar_list", "List upcoming calendar events"),
            make_tool("obsidian_note", "Create or edit an Obsidian note"),
            make_tool("obsidian_search", "Search Obsidian vault notes"),
            make_tool("weather_current", "Get current weather conditions"),
            make_tool("weather_forecast", "Get a weather forecast"),
            make_tool("file_read", "Read the contents of a file"),
            make_tool("file_write", "Write content to a file"),
        ]
        return build_index(tools)

    def test_returns_relevant_tools(self):
        strategy = BM25SearchStrategy()
        entries = self._make_entries()
        results = strategy.search("email", entries, top_k=3)
        names = [t.name for t in results]
        assert "send_email" in names or "read_email" in names

    def test_top_k_limit(self):
        strategy = BM25SearchStrategy()
        entries = self._make_entries()
        results = strategy.search("calendar event", entries, top_k=2)
        assert len(results) <= 2

    def test_no_match_returns_empty(self):
        strategy = BM25SearchStrategy()
        entries = self._make_entries()
        results = strategy.search("xyzzy_nonexistent_token_9999", entries, top_k=5)
        assert results == []

    def test_empty_entries(self):
        strategy = BM25SearchStrategy()
        assert strategy.search("anything", [], top_k=5) == []

    def test_empty_query(self):
        strategy = BM25SearchStrategy()
        entries = self._make_entries()
        assert strategy.search("", entries, top_k=5) == []

    def test_most_relevant_ranked_first(self):
        strategy = BM25SearchStrategy()
        entries = self._make_entries()
        results = strategy.search("obsidian note", entries, top_k=3)
        names = [t.name for t in results]
        # obsidian_note is an exact name+description match; should rank highest
        assert names[0] in ("obsidian_note", "obsidian_search")


# ---------------------------------------------------------------------------
# RegexSearchStrategy
# ---------------------------------------------------------------------------

class TestRegexSearchStrategy:
    def test_finds_matching_tool(self):
        strategy = RegexSearchStrategy()
        tools = [
            make_tool("gmail_send", "Send a gmail message"),
            make_tool("slack_post", "Post a slack message"),
        ]
        results = strategy.search("gmail", build_index(tools), top_k=5)
        assert len(results) == 1
        assert results[0].name == "gmail_send"

    def test_no_match(self):
        strategy = RegexSearchStrategy()
        tools = [make_tool("foo", "bar baz")]
        results = strategy.search("email", build_index(tools), top_k=5)
        assert results == []

    def test_multi_token_hits_rank_higher(self):
        strategy = RegexSearchStrategy()
        tools = [
            make_tool("a", "calendar event meeting"),
            make_tool("b", "calendar meeting"),
            make_tool("c", "event only"),
        ]
        results = strategy.search("calendar event meeting", build_index(tools), top_k=3)
        assert results[0].name == "a"


# ---------------------------------------------------------------------------
# ToolRegistry two-tier behaviour
# ---------------------------------------------------------------------------

class TestToolRegistryDeferred:
    def _make_registry(self):
        reg = ToolRegistry()
        reg.register(make_tool("live_a", "live tool a"))
        reg.register(make_tool("live_b", "live tool b"))
        reg.register(make_tool("live_c", "live tool c"))
        reg.register_deferred(make_tool("deferred_email", "send or receive email messages"))
        reg.register_deferred(make_tool("deferred_calendar", "create calendar events"))
        return reg

    def test_to_specs_excludes_deferred(self):
        reg = self._make_registry()
        specs = reg.to_specs()
        names = [s.name for s in specs]
        assert "live_a" in names
        assert "deferred_email" not in names
        assert "deferred_calendar" not in names

    def test_deferred_tool_count(self):
        reg = self._make_registry()
        assert reg.deferred_tool_count() == 2

    def test_has_deferred_tools(self):
        reg = self._make_registry()
        assert reg.has_deferred_tools() is True

    def test_search_and_load_promotes_tool(self):
        reg = self._make_registry()
        loaded = reg.search_and_load("email", top_k=5)
        assert len(loaded) == 1
        assert loaded[0].name == "deferred_email"

        # Now it should be in live specs
        specs = reg.to_specs()
        names = [s.name for s in specs]
        assert "deferred_email" in names

    def test_search_and_load_sticky(self):
        """Loading a tool twice returns empty list on the second call."""
        reg = self._make_registry()
        reg.search_and_load("email", top_k=5)
        second = reg.search_and_load("email", top_k=5)
        assert second == []

    def test_deferred_count_decreases_after_load(self):
        reg = self._make_registry()
        assert reg.deferred_tool_count() == 2
        reg.search_and_load("email", top_k=1)
        assert reg.deferred_tool_count() == 1

    def test_unregister_by_prefix_clears_both_tiers(self):
        reg = ToolRegistry()
        reg.register(make_tool("mcp_live", "live mcp tool"))
        reg.register_deferred(make_tool("mcp_deferred", "deferred mcp tool"))
        removed = reg.unregister_by_prefix("mcp_")
        assert removed == 2
        assert reg.deferred_tool_count() == 0
        assert reg.to_specs() == []

    def test_search_empty_deferred_returns_empty(self):
        reg = ToolRegistry()
        reg.register(make_tool("live_x", "something"))
        assert reg.search_and_load("anything") == []


# ---------------------------------------------------------------------------
# SearchToolsTool
# ---------------------------------------------------------------------------

class TestSearchToolsTool:
    def _make_registry_with_deferred(self):
        reg = ToolRegistry()
        reg.register_deferred(make_tool("gmail_send", "Send an email via Gmail"))
        reg.register_deferred(make_tool("calendar_create", "Create a Google Calendar event"))
        return reg

    @pytest.mark.asyncio
    async def test_loads_matching_tool(self):
        reg = self._make_registry_with_deferred()
        tool = SearchToolsTool(reg)
        result = await tool.execute({"query": "send email"})
        assert result.success is True
        assert "gmail_send" in result.output

    @pytest.mark.asyncio
    async def test_tool_becomes_live_after_search(self):
        reg = self._make_registry_with_deferred()
        tool = SearchToolsTool(reg)
        await tool.execute({"query": "email"})
        names = [s.name for s in reg.to_specs()]
        assert "gmail_send" in names

    @pytest.mark.asyncio
    async def test_no_match_returns_helpful_message(self):
        reg = self._make_registry_with_deferred()
        tool = SearchToolsTool(reg)
        result = await tool.execute({"query": "xyzzy_nonexistent"})
        assert result.success is True
        assert "No tools matched" in result.output

    @pytest.mark.asyncio
    async def test_empty_deferred_returns_no_tools_message(self):
        reg = ToolRegistry()  # no deferred tools
        tool = SearchToolsTool(reg)
        result = await tool.execute({"query": "email"})
        assert result.success is True
        assert "No additional tools" in result.output

    @pytest.mark.asyncio
    async def test_missing_query_returns_error(self):
        reg = self._make_registry_with_deferred()
        tool = SearchToolsTool(reg)
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# PromptBuilder deferred hint
# ---------------------------------------------------------------------------

class TestPromptBuilderDeferredHint:
    """Verify the system prompt hint is injected when deferred_tool_count > 0."""

    def _make_state(self):
        from proxi.core.state import AgentState, WorkspaceConfig
        import tempfile, os

        tmpdir = tempfile.mkdtemp()
        ws = WorkspaceConfig(
            agent_id="test",
            session_id="s1",
            workspace_root=tmpdir,
            global_system_prompt_path=os.path.join(tmpdir, "system_prompt.md"),
            soul_path=os.path.join(tmpdir, "Soul.md"),
            history_path=os.path.join(tmpdir, "history.jsonl"),
            plan_path=os.path.join(tmpdir, "plan.md"),
            todos_path=os.path.join(tmpdir, "todos.md"),
        )
        return AgentState(workspace=ws)

    def test_hint_present_when_deferred_tools_exist(self):
        from proxi.core.prompt_builder import PromptBuilder
        builder = PromptBuilder()
        state = self._make_state()
        payload = builder.build(state, tools=[], deferred_tool_count=3)
        assert payload.system is not None
        assert "search_tools" in payload.system
        assert "MUST call" in payload.system

    def test_hint_absent_when_no_deferred_tools(self):
        from proxi.core.prompt_builder import PromptBuilder
        builder = PromptBuilder()
        state = self._make_state()
        payload = builder.build(state, tools=[], deferred_tool_count=0)
        system = payload.system or ""
        assert "ADDITIONAL TOOLS AVAILABLE" not in system
