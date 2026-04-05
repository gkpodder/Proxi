"""Tests for integration catalog category and routing behavior."""

from proxi.integrations.catalog import known_integrations, tool_integration


def test_known_integrations_include_google_calendar() -> None:
    """Google Calendar integration is exposed to enable/disable interfaces."""
    integrations = known_integrations()
    assert "google_calendar" in integrations


def test_known_integrations_include_obsidian() -> None:
    """Obsidian integration is exposed to enable/disable interfaces."""
    integrations = known_integrations()
    assert "obsidian" in integrations


def test_known_integrations_include_spotify() -> None:
    """Spotify integration is exposed to enable/disable interfaces."""
    integrations = known_integrations()
    assert "spotify" in integrations


def test_calendar_tools_route_to_google_calendar() -> None:
    """Calendar-prefixed tool names route to the google_calendar integration."""
    assert tool_integration("calendar_list_events") == "google_calendar"
    assert tool_integration("calendar_create_event") == "google_calendar"
    assert tool_integration("calendar_get_event") == "google_calendar"
    assert tool_integration("calendar_update_event") == "google_calendar"
    assert tool_integration("calendar_delete_event") == "google_calendar"


def test_obsidian_tools_route_to_obsidian() -> None:
    """Obsidian-prefixed tool names route to the obsidian integration."""
    assert tool_integration("obsidian_list_vaults") == "obsidian"
    assert tool_integration("obsidian_list_notes") == "obsidian"
    assert tool_integration("obsidian_read_note") == "obsidian"
    assert tool_integration("obsidian_create_note") == "obsidian"
    assert tool_integration("obsidian_update_note") == "obsidian"
    assert tool_integration("obsidian_search_notes") == "obsidian"
    assert tool_integration("obsidian_get_note_metadata") == "obsidian"


def test_spotify_tools_route_to_spotify() -> None:
    """Spotify-prefixed tool names route to the spotify integration."""
    assert tool_integration("spotify_get_profile") == "spotify"
    assert tool_integration("spotify_get_playback") == "spotify"
    assert tool_integration("spotify_play") == "spotify"
    assert tool_integration("spotify_pause") == "spotify"
    assert tool_integration("spotify_next_track") == "spotify"
    assert tool_integration("spotify_previous_track") == "spotify"
    assert tool_integration("spotify_set_volume") == "spotify"
    assert tool_integration("spotify_search") == "spotify"
    assert tool_integration("spotify_list_playlists") == "spotify"
    assert tool_integration("spotify_play_playlist") == "spotify"
    assert tool_integration("spotify_add_track_to_playlist") == "spotify"
