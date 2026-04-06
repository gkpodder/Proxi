#!/usr/bin/env python3
"""Standalone MCP Server for Spotify."""

import asyncio
import json
import sys
from typing import Any

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

SPOTIFY_TOOLS = [
    {
        "name": "spotify_get_profile",
        "description": (
            "Get the Spotify profile for the connected account. "
            "Use this first to confirm Spotify OAuth is connected and which account is active."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_get_playback",
        "description": "Get current Spotify playback state including device and currently playing track.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_list_devices",
        "description": "List available Spotify playback devices.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_get_current_track",
        "description": "Get the URI/details of the currently playing Spotify track.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_play",
        "description": (
            "Start or resume Spotify playback. "
            "Optionally provide context_uri (album/artist/playlist URI), uris (track URIs), and device_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "track_uri": {"type": "string", "description": "Single Spotify track URI (compat alias for uris=[...])."},
                "context_uri": {"type": "string", "description": "Spotify context URI (e.g., spotify:playlist:...)."},
                "uris": {"type": "array", "items": {"type": "string"}, "description": "List of Spotify track URIs."},
                "device_id": {"type": "string", "description": "Optional Spotify device ID."},
                "device_name": {"type": "string", "description": "Optional Spotify device name."},
            },
            "required": [],
        },
    },
    {
        "name": "spotify_pause",
        "description": "Pause Spotify playback.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Optional Spotify device ID."},
                "device_name": {"type": "string", "description": "Optional Spotify device name."},
            },
            "required": [],
        },
    },
    {
        "name": "spotify_next_track",
        "description": "Skip to the next Spotify track.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Optional Spotify device ID."},
                "device_name": {"type": "string", "description": "Optional Spotify device name."},
            },
            "required": [],
        },
    },
    {
        "name": "spotify_previous_track",
        "description": "Go to the previous Spotify track.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Optional Spotify device ID."},
                "device_name": {"type": "string", "description": "Optional Spotify device name."},
            },
            "required": [],
        },
    },
    {
        "name": "spotify_set_volume",
        "description": "Set Spotify volume (0-100).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "volume_percent": {"type": "integer", "description": "Target volume from 0 to 100."},
                "device_id": {"type": "string", "description": "Optional Spotify device ID."},
                "device_name": {"type": "string", "description": "Optional Spotify device name."},
            },
            "required": ["volume_percent"],
        },
    },
    {
        "name": "spotify_search",
        "description": (
            "Search Spotify for tracks, artists, albums, or playlists. "
            "Use this to find URIs before starting playback or adding tracks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "search_type": {"type": "string", "description": "One of: track, artist, album, playlist."},
                "limit": {"type": "integer", "description": "Maximum results (1-50, default: 10)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "spotify_list_playlists",
        "description": "List playlists from the connected Spotify account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum playlists to return (1-50, default: 20)."},
            },
            "required": [],
        },
    },
    {
        "name": "spotify_get_playlist",
        "description": "Get details for a Spotify playlist, including owner and collaborative status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string", "description": "Spotify playlist ID."},
                "include_tracks": {"type": "boolean", "description": "Include playlist track items when Spotify allows it."},
            },
            "required": ["playlist_id"],
        },
    },
    {
        "name": "spotify_create_playlist",
        "description": "Create a playlist in the connected Spotify account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Playlist name."},
                "public": {"type": "boolean", "description": "Whether playlist should be public (default: false)."},
                "description": {"type": "string", "description": "Optional playlist description."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "spotify_play_playlist",
        "description": "Start playback for a playlist by playlist ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string", "description": "Spotify playlist ID."},
                "device_id": {"type": "string", "description": "Optional Spotify device ID."},
            },
            "required": ["playlist_id"],
        },
    },
    {
        "name": "spotify_add_track_to_playlist",
        "description": "Add a track URI to a playlist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string", "description": "Spotify playlist ID."},
                "track_uri": {"type": "string", "description": "Track URI (for example spotify:track:...)."},
            },
            "required": ["playlist_id", "track_uri"],
        },
    },
    {
        "name": "spotify_add_current_track_to_playlist",
        "description": "Add the currently playing track to a playlist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string", "description": "Spotify playlist ID."},
            },
            "required": ["playlist_id"],
        },
    },
    {
        "name": "spotify_queue_add",
        "description": (
            "Add a track or episode to the Spotify playback queue. "
            "Use this to queue something to play next without interrupting playback."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_uri": {"type": "string", "description": "Spotify track/episode URI to queue."},
                "track_uri": {"type": "string", "description": "Compat alias for item_uri."},
                "uri": {"type": "string", "description": "Compat alias for item_uri."},
                "device_id": {"type": "string", "description": "Optional Spotify device ID."},
                "device_name": {"type": "string", "description": "Optional Spotify device name."},
            },
            "required": [],
        },
    },
    {
        "name": "spotify_queue_next",
        "description": "Show the next item currently queued in Spotify and the full queue snapshot.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_list_queue",
        "description": "List the Spotify queue, including currently playing and upcoming items.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


class SpotifyMCPServer:
    """Standalone MCP server for Spotify operations."""

    def __init__(self) -> None:
        self._spotify: Any = None

    def _get_spotify(self) -> Any:
        from proxi.mcp.servers.spotify_tools import SpotifyTools
        if self._spotify is None:
            self._spotify = SpotifyTools()
        return self._spotify

    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "proxi-spotify-mcp", "version": "1.0.0"},
        }

    async def handle_tools_list(self) -> dict[str, Any]:
        return {"tools": SPOTIFY_TOOLS}

    async def handle_call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            spotify = self._get_spotify()

            if name == "spotify_get_profile":
                result = await spotify.get_profile()
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_get_playback":
                result = await spotify.get_current_playback()
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_list_devices":
                result = await spotify.list_devices()
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_get_current_track":
                result = await spotify.get_current_track_uri()
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_play":
                uris = arguments.get("uris") or arguments.get("track_uris")
                if uris is None and arguments.get("track_uri"):
                    uris = [arguments.get("track_uri")]

                device_id = arguments.get("device_id")
                device_name = arguments.get("device_name")
                if not device_id and device_name:
                    device_id = await spotify.resolve_device_id(device_name=device_name)

                result = await spotify.play(
                    context_uri=arguments.get("context_uri"),
                    uris=uris,
                    device_id=device_id,
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_pause":
                device_id = arguments.get("device_id")
                device_name = arguments.get("device_name")
                if not device_id and device_name:
                    device_id = await spotify.resolve_device_id(device_name=device_name)
                result = await spotify.pause(device_id=device_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_next_track":
                device_id = arguments.get("device_id")
                device_name = arguments.get("device_name")
                if not device_id and device_name:
                    device_id = await spotify.resolve_device_id(device_name=device_name)
                result = await spotify.next_track(device_id=device_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_previous_track":
                device_id = arguments.get("device_id")
                device_name = arguments.get("device_name")
                if not device_id and device_name:
                    device_id = await spotify.resolve_device_id(device_name=device_name)
                result = await spotify.previous_track(device_id=device_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_set_volume":
                if "volume_percent" not in arguments:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'volume_percent'"})}]}
                device_id = arguments.get("device_id")
                device_name = arguments.get("device_name")
                if not device_id and device_name:
                    device_id = await spotify.resolve_device_id(device_name=device_name)
                result = await spotify.set_volume(
                    volume_percent=int(arguments["volume_percent"]),
                    device_id=device_id,
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_search":
                query = arguments.get("query") or ""
                if not query.strip():
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'query'"})}]}
                result = await spotify.search(
                    query=query,
                    search_type=arguments.get("search_type", "track"),
                    limit=int(arguments.get("limit", arguments.get("max_results", 10))),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_list_playlists":
                result = await spotify.list_playlists(limit=int(arguments.get("limit", 20)))
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_get_playlist":
                playlist_id = (arguments.get("playlist_id") or "").strip()
                if not playlist_id:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'playlist_id'"})}]}
                result = await spotify.get_playlist(
                    playlist_id,
                    include_tracks=bool(arguments.get("include_tracks", False)),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_create_playlist":
                playlist_name = (arguments.get("name") or "").strip()
                if not playlist_name:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'name'"})}]}
                result = await spotify.create_playlist(
                    name=playlist_name,
                    public=bool(arguments.get("public", False)),
                    description=arguments.get("description"),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_play_playlist":
                playlist_id = (arguments.get("playlist_id") or "").strip()
                if not playlist_id:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'playlist_id'"})}]}
                result = await spotify.play_playlist(
                    playlist_id=playlist_id,
                    device_id=arguments.get("device_id"),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_add_track_to_playlist":
                playlist_id = (arguments.get("playlist_id") or "").strip()
                track_uri = (arguments.get("track_uri") or "").strip()
                if not playlist_id:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'playlist_id'"})}]}
                if not track_uri:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'track_uri'"})}]}
                result = await spotify.add_track_to_playlist(
                    playlist_id=playlist_id,
                    track_uri=track_uri,
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_add_current_track_to_playlist":
                playlist_id = (arguments.get("playlist_id") or "").strip()
                if not playlist_id:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'playlist_id'"})}]}
                result = await spotify.add_current_track_to_playlist(playlist_id=playlist_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_queue_add":
                item_uri = (
                    arguments.get("item_uri")
                    or arguments.get("track_uri")
                    or arguments.get("uri")
                    or ""
                ).strip()
                if not item_uri:
                    return {"content": [{"type": "text", "text": json.dumps({"error": "Missing required field: 'item_uri'"})}]}
                device_id = arguments.get("device_id")
                device_name = arguments.get("device_name")
                if not device_id and device_name:
                    device_id = await spotify.resolve_device_id(device_name=device_name)
                result = await spotify.add_to_queue(item_uri=item_uri, device_id=device_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "spotify_queue_next":
                result = await spotify.get_queue()
                payload = {
                    "next": result.get("next"),
                    "currently_playing": result.get("currently_playing"),
                    "count": result.get("count", 0),
                }
                return {"content": [{"type": "text", "text": json.dumps(payload)}]}

            if name == "spotify_list_queue":
                result = await spotify.get_queue()
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

        except Exception as e:
            logger.error("spotify_tool_error", tool=name, error=str(e))
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    async def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list()
            elif method == "tools/call":
                result = await self.handle_call_tool(
                    params.get("name", ""), params.get("arguments", {})
                )
            elif method == "notifications/initialized":
                return None
            else:
                result = {"error": f"Unknown method: {method}"}

            if msg_id is not None:
                return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            logger.error("spotify_server_message_error", error=str(e))
            if msg_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                }
        return None

    def run(self) -> None:
        logger.info("spotify_mcp_server_started")
        try:
            while True:
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    message = json.loads(line.strip())
                    response = asyncio.run(self.process_message(message))
                    if response:
                        sys.stdout.write(json.dumps(response) + "\n")
                        sys.stdout.flush()
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error("spotify_server_error", error=str(e))
        except KeyboardInterrupt:
            logger.info("spotify_mcp_server_stopped")
        except Exception as e:
            logger.error("spotify_server_fatal_error", error=str(e))
            sys.exit(1)


if __name__ == "__main__":
    server = SpotifyMCPServer()
    server.run()
