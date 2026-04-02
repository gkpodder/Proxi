"""Tests for the tool search / deferred loading feature."""

import json

import pytest

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.call_tool_tool import CallToolTool
from proxi.tools.registry import ToolRegistry
from proxi.tools.search import BM25SearchStrategy, RegexSearchStrategy, build_index


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

    def test_search_deferred_returns_toolspec(self):
        reg = self._make_registry()
        specs = reg.search_deferred("email", top_k=5)
        assert len(specs) == 1
        assert specs[0].name == "deferred_email"
        # Full schema must be present
        assert specs[0].description
        assert isinstance(specs[0].parameters, dict)

    def test_search_deferred_does_not_promote(self):
        """Deferred tools must never be promoted to the live tier."""
        reg = self._make_registry()
        reg.search_deferred("email", top_k=5)
        live_names = [s.name for s in reg.to_specs()]
        assert "deferred_email" not in live_names
        # Still in deferred tier
        assert reg.deferred_tool_count() == 2

    def test_search_deferred_deduplicates(self):
        """Second search for same tool returns empty (schema already injected)."""
        reg = self._make_registry()
        first = reg.search_deferred("email", top_k=5)
        assert len(first) == 1
        second = reg.search_deferred("email", top_k=5)
        assert second == []

    @pytest.mark.asyncio
    async def test_execute_deferred(self):
        reg = self._make_registry()
        result = await reg.execute_deferred("deferred_email", {})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_deferred_unknown_returns_error(self):
        reg = self._make_registry()
        result = await reg.execute_deferred("nonexistent_tool", {})
        assert result.success is False
        assert result.error is not None

    def test_unregister_by_prefix_clears_schema_injected(self):
        reg = ToolRegistry()
        reg.register_deferred(make_tool("mcp_deferred", "deferred mcp tool"))
        reg.search_deferred("mcp", top_k=5)
        assert "mcp_deferred" in reg._schema_injected
        reg.unregister_by_prefix("mcp_")
        assert "mcp_deferred" not in reg._schema_injected

    def test_unregister_by_prefix_clears_both_tiers(self):
        reg = ToolRegistry()
        reg.register(make_tool("mcp_live", "live mcp tool"))
        reg.register_deferred(make_tool("mcp_deferred", "deferred mcp tool"))
        removed = reg.unregister_by_prefix("mcp_")
        assert removed == 2
        assert reg.deferred_tool_count() == 0
        assert reg.to_specs() == []

    def test_search_deferred_empty_returns_empty(self):
        reg = ToolRegistry()
        reg.register(make_tool("live_x", "something"))
        assert reg.search_deferred("anything") == []


# ---------------------------------------------------------------------------
# CallToolTool — merged discovery + execution
# ---------------------------------------------------------------------------

class TestCallToolTool:
    def _make_registry(self):
        reg = ToolRegistry()
        reg.register_deferred(make_tool("gmail_send", "Send an email via Gmail"))
        reg.register_deferred(make_tool("calendar_create", "Create a Google Calendar event"))
        reg.register_deferred(make_tool("obsidian_create_note", "Create a note in Obsidian vault"))
        return reg

    @pytest.mark.asyncio
    async def test_exact_match_executes(self):
        reg = self._make_registry()
        ct = CallToolTool(reg)
        result = await ct.execute({"tool_name": "gmail_send", "args": {}})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_missing_tool_name_returns_error(self):
        reg = self._make_registry()
        ct = CallToolTool(reg)
        result = await ct.execute({"args": {}})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_does_not_dispatch_live_tools(self):
        """call_tool only dispatches deferred tools, not live ones."""
        reg = ToolRegistry()
        reg.register(make_tool("live_tool", "a live tool"))
        ct = CallToolTool(reg)
        result = await ct.execute({"tool_name": "live_tool", "args": {}})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_close_name_returns_suggestions_not_execution(self):
        """Fuzzy name should return suggestions, never auto-execute."""
        reg = self._make_registry()
        ct = CallToolTool(reg)
        # "gmail_send_email" is not an exact name but "gmail_send" is close
        result = await ct.execute({"tool_name": "gmail_send_email", "args": {}})
        assert result.success is False
        # Should suggest gmail_send but NOT have executed it
        assert "gmail_send" in result.error
        assert "Did you mean" in result.error

    @pytest.mark.asyncio
    async def test_completely_unrelated_name_returns_no_match(self):
        """Totally unrelated query should not suggest unrelated tools."""
        reg = self._make_registry()
        ct = CallToolTool(reg)
        result = await ct.execute({"tool_name": "xyzzy_totally_unrelated_9999", "args": {}})
        assert result.success is False
        # Should not suggest email/calendar/obsidian tools
        assert "Did you mean" not in (result.error or "") and "Did you mean" not in result.output

    @pytest.mark.asyncio
    async def test_tool_stays_deferred_after_suggestion(self):
        """Tools must never be promoted to live tier even after suggestion."""
        reg = self._make_registry()
        ct = CallToolTool(reg)
        await ct.execute({"tool_name": "gmail_send_email", "args": {}})
        live_names = [s.name for s in reg.to_specs()]
        assert "gmail_send" not in live_names


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
        assert "call_tool" in payload.system
        assert "AVAILABLE ON DEMAND" in payload.system

    def test_hint_absent_when_no_deferred_tools(self):
        from proxi.core.prompt_builder import PromptBuilder
        builder = PromptBuilder()
        state = self._make_state()
        payload = builder.build(state, tools=[], deferred_tool_count=0)
        system = payload.system or ""
        assert "ADDITIONAL TOOLS AVAILABLE" not in system

    def test_deferred_stubs_rendered_in_hint(self):
        from proxi.core.prompt_builder import PromptBuilder
        from proxi.llm.schemas import ToolSpec
        builder = PromptBuilder()
        state = self._make_state()
        stubs = [
            ToolSpec(name="mcp_obsidian_list_notes", description="List notes in Obsidian vault", parameters={}),
            ToolSpec(name="mcp_send_email", description="Send an email via Gmail", parameters={}),
        ]
        payload = builder.build(state, tools=[], deferred_tool_count=2, deferred_specs=stubs)
        assert payload.system is not None
        assert "mcp_obsidian_list_notes" in payload.system
        assert "mcp_send_email" in payload.system
        assert "AVAILABLE ON DEMAND" in payload.system
        # Descriptions should NOT appear — names only to save tokens
        assert "List notes in Obsidian vault" not in payload.system
        assert "Send an email via Gmail" not in payload.system
