"""Tests for MCP catalog category and routing behavior."""

from proxi.mcp.catalog import known_mcp_categories, tool_mcp_category


def test_known_categories_include_calendar() -> None:
    """Calendar category is exposed to MCP enable/disable interfaces."""
    categories = known_mcp_categories()
    assert "calendar" in categories


def test_known_categories_include_obsidian() -> None:
    """Obsidian category is exposed to MCP enable/disable interfaces."""
    categories = known_mcp_categories()
    assert "obsidian" in categories


def test_calendar_tools_route_to_calendar_category() -> None:
    """Calendar-prefixed tool names route to the calendar category."""
    assert tool_mcp_category("calendar_list_events") == "calendar"
    assert tool_mcp_category("calendar_create_event") == "calendar"
    assert tool_mcp_category("calendar_get_event") == "calendar"
    assert tool_mcp_category("calendar_update_event") == "calendar"
    assert tool_mcp_category("calendar_delete_event") == "calendar"


def test_obsidian_tools_route_to_obsidian_category() -> None:
    """Obsidian-prefixed tool names route to the obsidian category."""
    assert tool_mcp_category("obsidian_list_vaults") == "obsidian"
    assert tool_mcp_category("obsidian_list_notes") == "obsidian"
    assert tool_mcp_category("obsidian_read_note") == "obsidian"
    assert tool_mcp_category("obsidian_create_note") == "obsidian"
    assert tool_mcp_category("obsidian_update_note") == "obsidian"
    assert tool_mcp_category("obsidian_search_notes") == "obsidian"
    assert tool_mcp_category("obsidian_get_note_metadata") == "obsidian"
