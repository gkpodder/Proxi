"""Central catalog for MCP categories and tool-to-category mapping."""

from __future__ import annotations

from collections.abc import Iterable

# Single source of truth for MCP categories that can be toggled in UI/CLI.
MCP_CATEGORIES: tuple[str, ...] = (
    "proxi",
    "gmail",
    "calendar",
    "spotify",
    "notion",
    "weather",
    "obsidian",
)

# Prefix-based tool category routing.
TOOL_CATEGORY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("calendar_", "calendar"),
    ("spotify_", "spotify"),
    ("notion_", "notion"),
    ("weather_", "weather"),
    ("obsidian_", "obsidian"),
)

# Exact-name routing for legacy tools that do not use a category prefix.
TOOL_CATEGORY_EXACT: dict[str, str] = {
    "read_emails": "gmail",
    "send_email": "gmail",
    "get_email": "gmail",
}


def known_mcp_categories() -> tuple[str, ...]:
    """Return MCP categories that should be exposed in enable/disable interfaces."""
    return MCP_CATEGORIES


def tool_mcp_category(tool_name: str) -> str | None:
    """Resolve an MCP category from an MCP tool name."""
    exact = TOOL_CATEGORY_EXACT.get(tool_name)
    if exact:
        return exact

    for prefix, category in TOOL_CATEGORY_PREFIXES:
        if tool_name.startswith(prefix):
            return category
    return None


def normalize_mcp_names(names: Iterable[str]) -> list[str]:
    """Normalize MCP names for persistence and comparison."""
    return [name.strip().lower() for name in names if name and name.strip()]
