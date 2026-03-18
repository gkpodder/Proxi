"""Tests for MCP catalog category and routing behavior."""

from proxi.mcp.catalog import known_mcp_categories, tool_mcp_category


def test_known_categories_include_calendar() -> None:
    """Calendar category is exposed to MCP enable/disable interfaces."""
    categories = known_mcp_categories()
    assert "calendar" in categories


def test_calendar_tools_route_to_calendar_category() -> None:
    """Calendar-prefixed tool names route to the calendar category."""
    assert tool_mcp_category("calendar_list_events") == "calendar"
    assert tool_mcp_category("calendar_create_event") == "calendar"
    assert tool_mcp_category("calendar_get_event") == "calendar"
    assert tool_mcp_category("calendar_update_event") == "calendar"
    assert tool_mcp_category("calendar_delete_event") == "calendar"
