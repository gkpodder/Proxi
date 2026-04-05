"""Spotify Web API tools for MCP server."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

load_dotenv()

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_ACCOUNTS_BASE = "https://accounts.spotify.com"
SPOTIFY_DEFAULT_SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-read-private",
    "user-read-email",
]
SPOTIFY_REQUIRED_SCOPE_SET = set(SPOTIFY_DEFAULT_SCOPES)


@dataclass
class _OAuthResult:
    """Captured OAuth callback result."""

    code: str | None = None
    state: str | None = None
    error: str | None = None


class SpotifyTools:
    """Tools for interacting with the Spotify Web API."""

    def __init__(self) -> None:
        self.client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
        self.client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
        self.redirect_uri = (
            os.getenv("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8888/callback"
        ).strip()
        self.token_path = Path(
            (os.getenv("SPOTIFY_TOKEN_PATH") or "config/spotify_token.json").strip()
        )

        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "Spotify credentials are missing. Set SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET in your environment."
            )

    def _basic_auth_header(self) -> str:
        payload = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(payload).decode("utf-8")

    def _load_token(self) -> dict[str, Any] | None:
        if not self.token_path.exists():
            return None
        try:
            with self.token_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("spotify_token_load_error", error=str(exc))
            return None

    def _save_token(self, token_data: dict[str, Any]) -> None:
        token_data = dict(token_data)
        expires_in = int(token_data.get("expires_in") or 3600)
        token_data["expires_at"] = int(time.time()) + expires_in
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with self.token_path.open("w", encoding="utf-8") as f:
            json.dump(token_data, f)

    @staticmethod
    def _token_scopes(token_data: dict[str, Any] | None) -> set[str]:
        if not token_data:
            return set()
        raw = str(token_data.get("scope") or "").strip()
        if not raw:
            return set()
        return {scope for scope in raw.split() if scope}

    def _has_required_scopes(self, token_data: dict[str, Any] | None) -> bool:
        token_scopes = self._token_scopes(token_data)
        return SPOTIFY_REQUIRED_SCOPE_SET.issubset(token_scopes)

    def _token_is_valid(self, token_data: dict[str, Any]) -> bool:
        access_token = token_data.get("access_token")
        expires_at = int(token_data.get("expires_at") or 0)
        return bool(access_token) and (expires_at - 60) > int(time.time())

    def _refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        response = requests.post(
            f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "Authorization": self._basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=20,
        )
        response.raise_for_status()
        refreshed = response.json()
        # Spotify may not return refresh_token for refresh grants.
        refreshed.setdefault("refresh_token", refresh_token)
        self._save_token(refreshed)
        return refreshed

    def _run_oauth_flow(self) -> dict[str, Any]:
        parsed = urlparse(self.redirect_uri)
        if not parsed.hostname or not parsed.port:
            raise RuntimeError(
                "SPOTIFY_REDIRECT_URI must include host and port, for example "
                "http://127.0.0.1:8888/callback"
            )

        result = _OAuthResult()
        expected_state = secrets.token_urlsafe(20)

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                query = parse_qs(urlparse(self.path).query)
                result.code = (query.get("code") or [None])[0]
                result.state = (query.get("state") or [None])[0]
                result.error = (query.get("error") or [None])[0]
                body = (
                    "Spotify authorization received. You can close this tab and return to Proxi."
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, _format: str, *_args: object) -> None:
                return

        scope = " ".join(SPOTIFY_DEFAULT_SCOPES)
        auth_url = (
            f"{SPOTIFY_ACCOUNTS_BASE}/authorize?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self.client_id,
                    "redirect_uri": self.redirect_uri,
                    "scope": scope,
                    "show_dialog": "true",
                    "state": expected_state,
                }
            )
        )

        server = HTTPServer((parsed.hostname, parsed.port), _CallbackHandler)
        server.timeout = 180

        logger.info("spotify_oauth_browser_open", redirect_uri=self.redirect_uri)
        webbrowser.open(auth_url)
        server.handle_request()
        server.server_close()

        if result.error:
            raise RuntimeError(f"Spotify OAuth failed: {result.error}")
        if not result.code:
            raise RuntimeError("Spotify OAuth timed out waiting for authorization callback")
        if result.state != expected_state:
            raise RuntimeError("Spotify OAuth state mismatch. Please try again.")

        token_resp = requests.post(
            f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
            data={
                "grant_type": "authorization_code",
                "code": result.code,
                "redirect_uri": self.redirect_uri,
            },
            headers={
                "Authorization": self._basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=20,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        self._save_token(token_data)
        logger.info("spotify_authenticated")
        return token_data

    def _ensure_access_token(self) -> str:
        token_data = self._load_token()
        if token_data and self._token_is_valid(token_data) and self._has_required_scopes(token_data):
            return str(token_data["access_token"])

        # A refresh grant cannot add new scopes, so we only refresh when scope set is already sufficient.
        if (
            token_data
            and token_data.get("refresh_token")
            and self._has_required_scopes(token_data)
        ):
            try:
                refreshed = self._refresh_access_token(str(token_data["refresh_token"]))
                return str(refreshed["access_token"])
            except requests.RequestException as exc:
                logger.warning("spotify_token_refresh_error", error=str(exc))

        new_token = self._run_oauth_flow()
        access_token = new_token.get("access_token")
        if not access_token:
            raise RuntimeError("Spotify token exchange did not return an access token")
        return str(access_token)

    def _spotify_request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        expected_statuses: set[int] | None = None,
    ) -> requests.Response:
        url = f"{SPOTIFY_API_BASE}{endpoint}"

        # Single retry path to recover from expired/missing-scope tokens.
        for attempt in range(2):
            token = self._ensure_access_token()
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=25,
            )

            if response.status_code in {401, 403} and attempt == 0:
                # Force full re-auth once for auth/scope issues.
                try:
                    body = response.json()
                except Exception:
                    body = {}
                message = str(((body.get("error") or {}).get("message") or "")).lower()
                if "scope" in message or "token" in message or response.status_code == 401:
                    logger.warning("spotify_auth_retry_reauthorize", status=response.status_code)
                    self._run_oauth_flow()
                    continue

            break

        allowed = expected_statuses or {200}
        if response.status_code not in allowed:
            detail = ""
            message = ""
            reason = ""
            try:
                payload = response.json()
                err_obj = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(err_obj, dict):
                    message = str(err_obj.get("message") or "")
                    reason = str(err_obj.get("reason") or "")
                elif err_obj is not None:
                    message = str(err_obj)
                else:
                    message = str(payload)
                detail = message
                if reason:
                    detail = f"{message} (reason: {reason})"
            except Exception:
                try:
                    detail = response.text
                except Exception:
                    detail = "(no response body)"

            hint = ""
            lower_detail = detail.lower()
            if response.status_code == 403:
                if "scope" in lower_detail or "insufficient" in lower_detail:
                    hint = (
                        " Hint: Re-authorize Spotify and grant playlist/read-playback scopes."
                    )
                else:
                    hint = (
                        " Hint: If your Spotify app is in Development mode, add your Spotify account "
                        "under Dashboard -> Users and Access, then re-authorize."
                    )
            raise RuntimeError(
                f"Spotify API request failed ({response.status_code}): {detail}{hint}"
            )

        return response

    async def get_current_track_uri(self) -> dict[str, Any]:
        """Get the currently playing track URI, if any."""
        response = self._spotify_request(
            "GET",
            "/me/player/currently-playing",
            expected_statuses={200, 204},
        )
        if response.status_code == 204:
            return {"track_uri": None, "message": "No current track"}

        payload = response.json()
        item = payload.get("item") or {}
        return {
            "track_uri": item.get("uri"),
            "track_name": item.get("name"),
            "artists": ", ".join(artist.get("name", "") for artist in item.get("artists", [])),
        }

    async def list_devices(self) -> dict[str, Any]:
        """List available Spotify playback devices for the connected account."""
        response = self._spotify_request("GET", "/me/player/devices")
        items = response.json().get("devices", [])
        devices = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "is_active": item.get("is_active"),
                "is_private_session": item.get("is_private_session"),
                "volume_percent": item.get("volume_percent"),
            }
            for item in items
        ]
        return {"devices": devices, "count": len(devices)}

    async def resolve_device_id(self, device_name: str | None = None) -> str | None:
        """Resolve a device name to a Spotify device_id, or return active device if omitted."""
        response = self._spotify_request("GET", "/me/player/devices")
        devices = response.json().get("devices", [])

        if not devices:
            return None

        if device_name and device_name.strip():
            wanted = device_name.strip().lower()
            for device in devices:
                if (device.get("name") or "").strip().lower() == wanted:
                    return device.get("id")

        for device in devices:
            if device.get("is_active"):
                return device.get("id")

        # Fallback to first available device if there is no active one.
        return devices[0].get("id")

    async def get_current_playback(self) -> dict[str, Any]:
        """Get current playback state and track details."""
        response = self._spotify_request(
            "GET",
            "/me/player",
            expected_statuses={200, 204},
        )
        if response.status_code == 204:
            return {"is_playing": False, "message": "No active playback"}

        payload = response.json()
        item = payload.get("item") or {}
        artists = ", ".join(artist.get("name", "") for artist in item.get("artists", []))
        return {
            "is_playing": payload.get("is_playing", False),
            "device": (payload.get("device") or {}).get("name"),
            "progress_ms": payload.get("progress_ms"),
            "repeat_state": payload.get("repeat_state"),
            "shuffle_state": payload.get("shuffle_state"),
            "track": {
                "name": item.get("name"),
                "artists": artists,
                "album": (item.get("album") or {}).get("name"),
                "uri": item.get("uri"),
                "duration_ms": item.get("duration_ms"),
            },
        }

    async def play(
        self,
        context_uri: str | None = None,
        uris: list[str] | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Start or resume playback."""
        body: dict[str, Any] = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris

        if device_id:
            # Transfer first to reduce false-success responses where play targets another device.
            self._spotify_request(
                "PUT",
                "/me/player",
                json_body={"device_ids": [device_id], "play": False},
                expected_statuses={200, 202, 204},
            )

        params = {"device_id": device_id} if device_id else None
        self._spotify_request(
            "PUT",
            "/me/player/play",
            params=params,
            json_body=body if body else None,
            expected_statuses={200, 202, 204},
        )

        # Verify state so callers can report real outcome instead of optimistic success.
        now_playing = None
        target_uri = uris[0] if uris else None
        matched_target: bool | None = None
        if target_uri:
            matched_target = False
        for _ in range(5):
            await asyncio.sleep(0.25)
            state = await self.get_current_playback()
            track = state.get("track") if isinstance(state, dict) else None
            current_uri = (track or {}).get("uri") if isinstance(track, dict) else None
            now_playing = state

            if target_uri:
                if current_uri == target_uri:
                    matched_target = True
                    break
                continue

            # Resume/pause flow: accept when device reports playing.
            if state.get("is_playing"):
                break

        result: dict[str, Any] = {
            "status": "ok",
            "action": "play",
            "verified": (
                bool(matched_target)
                if matched_target is not None
                else bool(now_playing and now_playing.get("is_playing"))
            ),
        }
        if target_uri:
            result["requested_track_uri"] = target_uri
        if now_playing:
            result["now_playing"] = now_playing.get("track")
            result["device"] = now_playing.get("device")
            result["is_playing"] = now_playing.get("is_playing")

        if target_uri and matched_target is False:
            result["warning"] = (
                "Spotify acknowledged the play command but current playback did not switch "
                "to the requested track yet."
            )

        return result

    async def pause(self, device_id: str | None = None) -> dict[str, Any]:
        """Pause current playback."""
        params = {"device_id": device_id} if device_id else None
        self._spotify_request(
            "PUT",
            "/me/player/pause",
            params=params,
            expected_statuses={200, 202, 204},
        )
        return {"status": "ok", "action": "pause"}

    async def next_track(self, device_id: str | None = None) -> dict[str, Any]:
        """Skip to the next track."""
        params = {"device_id": device_id} if device_id else None
        self._spotify_request(
            "POST",
            "/me/player/next",
            params=params,
            expected_statuses={200, 202, 204},
        )
        return {"status": "ok", "action": "next_track"}

    async def previous_track(self, device_id: str | None = None) -> dict[str, Any]:
        """Skip to the previous track."""
        params = {"device_id": device_id} if device_id else None
        self._spotify_request(
            "POST",
            "/me/player/previous",
            params=params,
            expected_statuses={200, 202, 204},
        )
        return {"status": "ok", "action": "previous_track"}

    async def set_volume(self, volume_percent: int, device_id: str | None = None) -> dict[str, Any]:
        """Set playback volume between 0 and 100."""
        if volume_percent < 0 or volume_percent > 100:
            return {"error": "volume_percent must be between 0 and 100"}

        params: dict[str, Any] = {"volume_percent": volume_percent}
        if device_id:
            params["device_id"] = device_id
        self._spotify_request(
            "PUT",
            "/me/player/volume",
            params=params,
            expected_statuses={200, 202, 204},
        )
        return {"status": "ok", "action": "set_volume", "volume_percent": volume_percent}

    async def search(self, query: str, search_type: str = "track", limit: int = 10) -> dict[str, Any]:
        """Search Spotify for tracks, artists, albums, or playlists."""
        allowed_types = {"track", "artist", "album", "playlist"}
        if search_type not in allowed_types:
            return {"error": f"search_type must be one of: {sorted(allowed_types)}"}

        response = self._spotify_request(
            "GET",
            "/search",
            params={
                "q": query,
                "type": search_type,
                "limit": max(1, min(limit, 50)),
            },
        )
        payload = response.json()

        key = f"{search_type}s"
        items = ((payload.get(key) or {}).get("items") or [])

        if search_type == "track":
            results = [
                {
                    "name": item.get("name"),
                    "uri": item.get("uri"),
                    "artists": ", ".join(
                        artist.get("name", "") for artist in item.get("artists", [])
                    ),
                    "album": (item.get("album") or {}).get("name"),
                }
                for item in items
            ]
        elif search_type == "playlist":
            results = [
                {
                    "name": item.get("name"),
                    "id": item.get("id"),
                    "uri": item.get("uri"),
                    "owner": (item.get("owner") or {}).get("display_name"),
                }
                for item in items
            ]
        else:
            results = [
                {
                    "name": item.get("name"),
                    "id": item.get("id"),
                    "uri": item.get("uri"),
                }
                for item in items
            ]

        return {
            "type": search_type,
            "count": len(results),
            "results": results,
        }

    async def list_playlists(self, limit: int = 20) -> dict[str, Any]:
        """List playlists from the connected Spotify account."""
        response = self._spotify_request(
            "GET",
            "/me/playlists",
            params={"limit": max(1, min(limit, 50))},
        )
        items = response.json().get("items", [])
        playlists = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "uri": item.get("uri"),
                "tracks_total": (item.get("tracks") or {}).get("total"),
                "public": item.get("public"),
            }
            for item in items
        ]
        return {"playlists": playlists, "count": len(playlists)}

    async def create_playlist(
        self,
        name: str,
        public: bool = False,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a playlist under the connected Spotify account."""
        me = self._spotify_request("GET", "/me").json()
        user_id = me.get("id")
        if not user_id:
            return {"error": "Could not resolve Spotify user id"}

        response = self._spotify_request(
            "POST",
            f"/users/{user_id}/playlists",
            json_body={
                "name": name,
                "public": bool(public),
                "description": description or "Created by Proxi",
            },
            expected_statuses={200, 201},
        )
        payload = response.json()
        return {
            "status": "ok",
            "id": payload.get("id"),
            "name": payload.get("name"),
            "uri": payload.get("uri"),
            "external_url": ((payload.get("external_urls") or {}).get("spotify")),
        }

    async def add_current_track_to_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Add the currently playing track to a playlist."""
        current = await self.get_current_track_uri()
        track_uri = current.get("track_uri")
        if not track_uri:
            return {
                "error": "No currently playing track found to add.",
                "details": current,
            }
        added = await self.add_track_to_playlist(playlist_id=playlist_id, track_uri=str(track_uri))
        added["current_track"] = {
            "track_uri": track_uri,
            "track_name": current.get("track_name"),
            "artists": current.get("artists"),
        }
        return added

    async def play_playlist(self, playlist_id: str, device_id: str | None = None) -> dict[str, Any]:
        """Start playback for a playlist by playlist ID."""
        context_uri = f"spotify:playlist:{playlist_id}"
        return await self.play(context_uri=context_uri, device_id=device_id)

    async def add_track_to_playlist(self, playlist_id: str, track_uri: str) -> dict[str, Any]:
        """Add a track URI to a playlist."""
        response = self._spotify_request(
            "POST",
            f"/playlists/{playlist_id}/tracks",
            json_body={"uris": [track_uri]},
            expected_statuses={200, 201},
        )
        payload = response.json()
        return {
            "status": "ok",
            "playlist_id": playlist_id,
            "track_uri": track_uri,
            "snapshot_id": payload.get("snapshot_id"),
        }

    async def get_profile(self) -> dict[str, Any]:
        """Get the profile for the connected Spotify account."""
        response = self._spotify_request("GET", "/me")
        payload = response.json()
        return {
            "id": payload.get("id"),
            "display_name": payload.get("display_name"),
            "email": payload.get("email"),
            "country": payload.get("country"),
            "product": payload.get("product"),
        }
