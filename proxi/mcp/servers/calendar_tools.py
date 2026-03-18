"""Google Calendar API tools for MCP server."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarTools:
    """Tools for interacting with Google Calendar API."""

    def __init__(self) -> None:
        """Initialize Calendar tools with credentials."""
        self.service = None
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate with Google Calendar API using OAuth 2.0."""
        token_path = os.getenv("CALENDAR_TOKEN_PATH", "calendar_token.json")
        client_id = os.getenv("CALENDAR_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID")
        client_secret = os.getenv("CALENDAR_CLIENT_SECRET") or os.getenv("GMAIL_CLIENT_SECRET")
        redirect_uri = os.getenv("CALENDAR_REDIRECT_URI") or os.getenv(
            "GMAIL_REDIRECT_URI", "http://localhost:8765"
        )

        if not client_id or not client_secret:
            raise RuntimeError(
                "Calendar credentials are missing. Set CALENDAR_CLIENT_ID and "
                "CALENDAR_CLIENT_SECRET (or reuse Gmail credentials)."
            )

        creds = None

        if Path(token_path).exists():
            try:
                with open(token_path, "r") as token_file:
                    token_data = json.load(token_file)
                    creds = Credentials.from_authorized_user_info(token_data)
            except Exception as e:
                logger.warning("calendar_token_load_error", error=str(e))

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://accounts.google.com/o/oauth2/token",
                        "redirect_uris": [redirect_uri],
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                creds = flow.run_local_server(port=8765)

            if creds:
                token_data = json.loads(creds.to_json())
                with open(token_path, "w") as token_file:
                    json.dump(token_data, token_file)

        self.service = build("calendar", "v3", credentials=creds)
        logger.info("calendar_authenticated")

    @staticmethod
    def _default_time_min() -> str:
        """Return current time in RFC3339 format for default event listing."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_rfc3339(value: str) -> datetime:
        """Parse RFC3339 datetime strings including Z suffix."""
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)

    async def list_events(
        self,
        max_results: int = 10,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """List upcoming events from a Google Calendar."""
        try:
            if not self.service:
                return {"error": "Calendar service not initialized"}

            kwargs: dict[str, Any] = {
                "calendarId": calendar_id,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
                "timeMin": time_min or self._default_time_min(),
            }
            if time_max:
                kwargs["timeMax"] = time_max
            if query:
                kwargs["q"] = query

            result = self.service.events().list(**kwargs).execute()
            items = result.get("items", [])

            events = []
            for item in items:
                start = item.get("start", {})
                end = item.get("end", {})
                events.append(
                    {
                        "id": item.get("id"),
                        "summary": item.get("summary", "(No Title)"),
                        "description": item.get("description", ""),
                        "location": item.get("location", ""),
                        "status": item.get("status", ""),
                        "html_link": item.get("htmlLink", ""),
                        "start": start.get("dateTime") or start.get("date"),
                        "end": end.get("dateTime") or end.get("date"),
                    }
                )

            return {"events": events, "count": len(events), "calendar_id": calendar_id}

        except HttpError as e:
            logger.error("calendar_list_error", error=str(e), calendar_id=calendar_id)
            return {"error": f"Calendar API error: {str(e)}"}

    async def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        timezone_name: str,
        calendar_id: str = "primary",
        attendees: list[str] | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Create a Google Calendar event."""
        try:
            if not self.service:
                return {"error": "Calendar service not initialized"}

            try:
                start_dt = self._parse_rfc3339(start_time)
                end_dt = self._parse_rfc3339(end_time)
            except ValueError:
                return {
                    "needs_clarification": True,
                    "invalid_fields": ["start_time", "end_time"],
                    "message": "Start and end times must be valid RFC3339 datetime values.",
                }

            if end_dt <= start_dt:
                return {
                    "needs_clarification": True,
                    "invalid_fields": ["end_time"],
                    "message": "End time must be later than start time.",
                }

            event: dict[str, Any] = {
                "summary": summary,
                "start": {"dateTime": start_time, "timeZone": timezone_name},
                "end": {"dateTime": end_time, "timeZone": timezone_name},
            }
            if attendees:
                event["attendees"] = [{"email": email} for email in attendees if email]
            if description:
                event["description"] = description
            if location:
                event["location"] = location

            created = self.service.events().insert(calendarId=calendar_id, body=event).execute()
            logger.info("calendar_event_created", event_id=created.get("id"), calendar_id=calendar_id)

            return {
                "status": "created",
                "event_id": created.get("id"),
                "calendar_id": calendar_id,
                "summary": created.get("summary", summary),
                "html_link": created.get("htmlLink", ""),
                "start": (created.get("start", {}) or {}).get("dateTime"),
                "end": (created.get("end", {}) or {}).get("dateTime"),
            }

        except HttpError as e:
            logger.error("calendar_create_error", error=str(e), calendar_id=calendar_id)
            return {"error": f"Calendar API error: {str(e)}"}

    async def get_event(self, event_id: str, calendar_id: str = "primary") -> dict[str, Any]:
        """Get details of a specific Google Calendar event."""
        try:
            if not self.service:
                return {"error": "Calendar service not initialized"}

            event = self.service.events().get(calendarId=calendar_id, eventId=event_id).execute()

            start = event.get("start", {})
            end = event.get("end", {})
            return {
                "id": event.get("id"),
                "calendar_id": calendar_id,
                "summary": event.get("summary", "(No Title)"),
                "description": event.get("description", ""),
                "location": event.get("location", ""),
                "status": event.get("status", ""),
                "html_link": event.get("htmlLink", ""),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "attendees": event.get("attendees", []),
            }

        except HttpError as e:
            logger.error("calendar_get_error", error=str(e), event_id=event_id)
            return {"error": f"Calendar API error: {str(e)}"}

    async def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        timezone_name: str | None = None,
        attendees: list[str] | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Update fields of an existing Google Calendar event."""
        try:
            if not self.service:
                return {"error": "Calendar service not initialized"}

            event = self.service.events().get(calendarId=calendar_id, eventId=event_id).execute()

            if summary is not None:
                event["summary"] = summary
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location

            if start_time is not None or end_time is not None:
                existing_start = (event.get("start", {}) or {}).get("dateTime")
                existing_end = (event.get("end", {}) or {}).get("dateTime")
                final_start = start_time or existing_start
                final_end = end_time or existing_end

                if not final_start or not final_end:
                    return {
                        "needs_clarification": True,
                        "invalid_fields": ["start_time", "end_time"],
                        "message": "Both start and end time must be available to update time.",
                    }

                try:
                    start_dt = self._parse_rfc3339(final_start)
                    end_dt = self._parse_rfc3339(final_end)
                except ValueError:
                    return {
                        "needs_clarification": True,
                        "invalid_fields": ["start_time", "end_time"],
                        "message": "Start and end times must be valid RFC3339 datetime values.",
                    }

                if end_dt <= start_dt:
                    return {
                        "needs_clarification": True,
                        "invalid_fields": ["end_time"],
                        "message": "End time must be later than start time.",
                    }

                final_timezone = timezone_name
                if not final_timezone:
                    final_timezone = (
                        (event.get("start", {}) or {}).get("timeZone")
                        or (event.get("end", {}) or {}).get("timeZone")
                        or "UTC"
                    )

                event["start"] = {"dateTime": final_start, "timeZone": final_timezone}
                event["end"] = {"dateTime": final_end, "timeZone": final_timezone}
            elif timezone_name:
                # If only timezone is changed, apply to existing dateTime values where present.
                if (event.get("start", {}) or {}).get("dateTime"):
                    event["start"]["timeZone"] = timezone_name
                if (event.get("end", {}) or {}).get("dateTime"):
                    event["end"]["timeZone"] = timezone_name

            if attendees is not None:
                event["attendees"] = [{"email": email} for email in attendees if email]

            updated = self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
            ).execute()

            logger.info("calendar_event_updated", event_id=event_id, calendar_id=calendar_id)
            return {
                "status": "updated",
                "event_id": updated.get("id", event_id),
                "calendar_id": calendar_id,
                "summary": updated.get("summary", ""),
                "html_link": updated.get("htmlLink", ""),
                "start": (updated.get("start", {}) or {}).get("dateTime"),
                "end": (updated.get("end", {}) or {}).get("dateTime"),
            }

        except HttpError as e:
            logger.error("calendar_update_error", error=str(e), event_id=event_id)
            return {"error": f"Calendar API error: {str(e)}"}

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> dict[str, Any]:
        """Delete an event from Google Calendar."""
        try:
            if not self.service:
                return {"error": "Calendar service not initialized"}

            self.service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.info("calendar_event_deleted", event_id=event_id, calendar_id=calendar_id)
            return {
                "status": "deleted",
                "event_id": event_id,
                "calendar_id": calendar_id,
            }
        except HttpError as e:
            logger.error("calendar_delete_error", error=str(e), event_id=event_id)
            return {"error": f"Calendar API error: {str(e)}"}