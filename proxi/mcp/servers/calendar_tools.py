"""Google Calendar API tools for MCP server."""

import difflib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

load_dotenv()

SHARED_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


class CalendarTools:
    """Tools for interacting with Google Calendar API."""

    def __init__(self) -> None:
        """Initialize Calendar tools with credentials."""
        self.service = None
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate with Google Calendar API using OAuth 2.0."""
        token_path = (
            os.getenv("GOOGLE_TOKEN_PATH")
            or os.getenv("CALENDAR_TOKEN_PATH")
            or os.getenv("GMAIL_TOKEN_PATH")
            or "config/google_token.json"
        )
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

        if not creds or not creds.valid or not creds.has_scopes(SHARED_GOOGLE_SCOPES):
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
                flow = InstalledAppFlow.from_client_config(client_config, SHARED_GOOGLE_SCOPES)
                creds = flow.run_local_server(port=8765)

            if creds:
                token_data = json.loads(creds.to_json())
                Path(token_path).parent.mkdir(parents=True, exist_ok=True)
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

    @staticmethod
    def _normalize_timezone(raw_timezone: str) -> str | None:
        """Resolve user-friendly timezone input to a valid IANA timezone name."""
        if not raw_timezone or not raw_timezone.strip():
            return None

        aliases = {
            "est": "America/New_York",
            "edt": "America/New_York",
            "eastern": "America/New_York",
            "eastern time": "America/New_York",
            "cst": "America/Chicago",
            "cdt": "America/Chicago",
            "central": "America/Chicago",
            "central time": "America/Chicago",
            "mst": "America/Denver",
            "mdt": "America/Denver",
            "mountain": "America/Denver",
            "mountain time": "America/Denver",
            "pst": "America/Los_Angeles",
            "pdt": "America/Los_Angeles",
            "pacific": "America/Los_Angeles",
            "pacific time": "America/Los_Angeles",
            "utc": "UTC",
            "gmt": "UTC",
        }

        raw = raw_timezone.strip()
        lowered = raw.lower()
        if lowered in aliases:
            return aliases[lowered]

        all_tzs = available_timezones()
        if raw in all_tzs:
            return raw

        # Normalize separators and case: "america/net york" -> "America/Net_York".
        normalized = raw.replace("\\", "/").replace("-", "_").strip()
        normalized = re.sub(r"\s+", "_", normalized)
        normalized = "/".join(part.capitalize() for part in normalized.split("/"))
        if normalized in all_tzs:
            return normalized

        # Fuzzy matching for common typos.
        tz_by_lower = {tz.lower(): tz for tz in all_tzs}
        fuzzy_target = normalized.lower()
        match = difflib.get_close_matches(
            fuzzy_target,
            list(tz_by_lower.keys()),
            n=1,
            cutoff=0.78,
        )
        if match:
            return tz_by_lower[match[0]]
        return None

    @staticmethod
    def _coerce_datetime_input(raw_value: str, timezone_name: str, fallback_date: datetime | None = None) -> str | None:
        """Convert RFC3339 or simple natural-time input to RFC3339."""
        value = (raw_value or "").strip()
        if not value:
            return None

        # Already RFC3339-ish
        try:
            parsed = CalendarTools._parse_rfc3339(value)
            return parsed.isoformat()
        except ValueError:
            pass

        tz = ZoneInfo(timezone_name)
        now_local = datetime.now(tz)
        date_hint = now_local.date()
        lower = value.lower()

        if "tomorrow" in lower or "tmr" in lower:
            date_hint = (now_local + timedelta(days=1)).date()
        elif fallback_date is not None:
            date_hint = fallback_date.astimezone(tz).date()

        # Accept inputs like "1030am", "10:30 am", "7pm", "17:00", "tomorrow at 5pm".
        match = re.search(r"(\d{1,2})(?::?(\d{2}))?\s*(am|pm)?", lower)
        if not match:
            return None

        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        ampm = (match.group(3) or "").lower()

        if minute > 59:
            return None

        if ampm:
            if hour < 1 or hour > 12:
                return None
            if ampm == "am":
                hour = 0 if hour == 12 else hour
            else:
                hour = 12 if hour == 12 else hour + 12
        else:
            if hour > 23:
                return None

        parsed_local = datetime(
            year=date_hint.year,
            month=date_hint.month,
            day=date_hint.day,
            hour=hour,
            minute=minute,
            tzinfo=tz,
        )
        return parsed_local.isoformat()

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

            resolved_timezone = self._normalize_timezone(timezone_name)
            if not resolved_timezone:
                return {
                    "needs_clarification": True,
                    "invalid_fields": ["timezone"],
                    "message": (
                        "Timezone is invalid. Use a city-based timezone like "
                        "America/New_York or America/Toronto."
                    ),
                }

            normalized_start = self._coerce_datetime_input(start_time, resolved_timezone)
            start_dt: datetime | None = None
            if normalized_start is not None:
                start_dt = self._parse_rfc3339(normalized_start)

            normalized_end = self._coerce_datetime_input(
                end_time,
                resolved_timezone,
                fallback_date=start_dt,
            )

            try:
                if normalized_start is None or normalized_end is None:
                    raise ValueError("missing normalized datetime")
                start_dt = self._parse_rfc3339(normalized_start)
                end_dt = self._parse_rfc3339(normalized_end)
            except ValueError:
                return {
                    "needs_clarification": True,
                    "invalid_fields": ["start_time", "end_time"],
                    "message": (
                        "Please provide recognizable start/end times. Examples: "
                        "'tomorrow 10:30am' and '11:00am'."
                    ),
                }

            if end_dt <= start_dt:
                return {
                    "needs_clarification": True,
                    "invalid_fields": ["end_time"],
                    "message": "End time must be later than start time.",
                }

            event: dict[str, Any] = {
                "summary": summary,
                "start": {"dateTime": normalized_start, "timeZone": resolved_timezone},
                "end": {"dateTime": normalized_end, "timeZone": resolved_timezone},
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