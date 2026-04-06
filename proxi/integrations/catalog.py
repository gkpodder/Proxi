"""Central catalog for integrations and tool-to-integration mapping."""

from __future__ import annotations

from collections.abc import Iterable

from proxi.integrations.interface import Integration

# All known integrations, keyed by integration name.
INTEGRATIONS: dict[str, Integration] = {
    "gmail": Integration(
        name="gmail",
        description="Gmail — read, send, and manage emails",
        type="cli",
        defer_loading=True,
        always_load=["read_emails"],
    ),
    "google_calendar": Integration(
        name="google_calendar",
        description="Google Calendar — manage events and schedules",
        type="cli",
        defer_loading=True,
        always_load=["calendar_list_events"],
    ),
    "spotify": Integration(
        name="spotify",
        description="Spotify — control music playback and manage playlists",
        type="cli",
        defer_loading=True,
        always_load=[],
    ),
    "notion": Integration(
        name="notion",
        description="Notion — read and write workspace pages",
        type="cli",
        defer_loading=True,
        always_load=[],
    ),
    "obsidian": Integration(
        name="obsidian",
        description="Obsidian — manage notes across vaults",
        type="cli",
        defer_loading=True,
        always_load=[],
    ),
    "weather": Integration(
        name="weather",
        description="Weather — current conditions and forecasts via Open-Meteo",
        type="cli",
        defer_loading=False,
        always_load=["get_weather"],
    ),
}

# Prefix-based tool → integration routing.
TOOL_INTEGRATION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("calendar_", "google_calendar"),
    ("spotify_", "spotify"),
    ("notion_", "notion"),
    ("weather_", "weather"),
    ("obsidian_", "obsidian"),
)

# Exact-name routing for tools that do not use an integration prefix.
TOOL_INTEGRATION_EXACT: dict[str, str] = {
    "read_emails": "gmail",
    "send_email": "gmail",
    "get_email": "gmail",
}


def known_integrations() -> tuple[str, ...]:
    """Return integration names that should be exposed in enable/disable interfaces."""
    return tuple(INTEGRATIONS.keys())


def tool_integration(tool_name: str) -> str | None:
    """Resolve an integration name from a tool name. Returns None for core tools."""
    exact = TOOL_INTEGRATION_EXACT.get(tool_name)
    if exact:
        return exact

    for prefix, integration_name in TOOL_INTEGRATION_PREFIXES:
        if tool_name.startswith(prefix):
            return integration_name
    return None


def normalize_integration_names(names: Iterable[str]) -> list[str]:
    """Normalize integration names for persistence and comparison."""
    return [name.strip().lower() for name in names if name and name.strip()]
