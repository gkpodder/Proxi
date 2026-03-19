#!/usr/bin/env python3
"""Combined MCP Server for Gmail, Calendar, Notion, Weather, and Obsidian."""

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

from proxi.observability.logging import get_logger

if TYPE_CHECKING:
    from proxi.mcp.servers.calendar_tools import CalendarTools
    from proxi.mcp.servers.gmail_tools import GmailTools
    from proxi.mcp.servers.notion_tools import NotionTools
    from proxi.mcp.servers.obsidian_tools import ObsidianTools
    from proxi.mcp.servers.weather_tools import WeatherTools

logger = get_logger(__name__)


class CombinedMCPServer:
    """MCP server for Gmail, Calendar, Notion, Weather, and Obsidian operations."""

    def __init__(self) -> None:
        """Initialize the combined MCP server."""
        self._gmail: "GmailTools | None" = None
        self._calendar: "CalendarTools | None" = None
        self._notion: "NotionTools | None" = None
        self._weather: "WeatherTools | None" = None
        self._obsidian: "ObsidianTools | None" = None

    def _get_gmail(self) -> "GmailTools":
        """Lazily initialize Gmail tools to avoid blocking initialize."""
        from proxi.mcp.servers.gmail_tools import GmailTools

        if self._gmail is None:
            self._gmail = GmailTools()
        return self._gmail

    def _get_notion(self) -> "NotionTools":
        """Lazily initialize Notion tools to avoid blocking initialize."""
        from proxi.mcp.servers.notion_tools import NotionTools

        if self._notion is None:
            self._notion = NotionTools()
        return self._notion

    def _get_calendar(self) -> "CalendarTools":
        """Lazily initialize Calendar tools to avoid blocking initialize."""
        from proxi.mcp.servers.calendar_tools import CalendarTools

        if self._calendar is None:
            self._calendar = CalendarTools()
        return self._calendar

    def _get_weather(self) -> "WeatherTools":
        """Lazily initialize Weather tools to avoid blocking initialize."""
        from proxi.mcp.servers.weather_tools import WeatherTools

        if self._weather is None:
            self._weather = WeatherTools()
        return self._weather

    def _get_obsidian(self) -> "ObsidianTools":
        """Lazily initialize Obsidian tools to avoid blocking initialize."""
        from proxi.mcp.servers.obsidian_tools import ObsidianTools

        if self._obsidian is None:
            self._obsidian = ObsidianTools()
        return self._obsidian

    @staticmethod
    def _calendar_clarification_response(
        missing_fields: list[str],
        invalid_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a structured clarification response for underspecified calendar requests."""
        invalid_fields = invalid_fields or []
        prompts = {
            "summary": "What is the exact event title?",
            "start_time": "What is the start time? Use RFC3339 (for example: 2026-03-19T14:00:00-04:00).",
            "end_time": "What is the end time? Use RFC3339 (for example: 2026-03-19T15:00:00-04:00).",
            "timezone": "What timezone should be used? Use IANA format (e.g., America/Toronto) — this is required for Google Calendar compatibility.",
            "attendees": "Who else should be invited? Provide a list of emails, or [] if no attendees.",
        }

        questions = [prompts[field] for field in missing_fields if field in prompts]
        if invalid_fields:
            for field in invalid_fields:
                if field in prompts and prompts[field] not in questions:
                    questions.append(prompts[field])

        message = "Need a few more details before I can create this calendar event."
        if invalid_fields:
            message = "Some event details are invalid or missing. Please clarify before creation."

        return {
            "needs_clarification": True,
            "missing_fields": missing_fields,
            "invalid_fields": invalid_fields,
            "questions": questions,
            "message": message,
        }

    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {
                "name": "proxi-mcp",
                "version": "1.0.0",
            },
        }

    async def handle_tools_list(self) -> dict[str, Any]:
        """Handle tools/list request."""
        return {
            "tools": [
                {
                    "name": "read_emails",
                    "description": (
                        "Read emails from Gmail inbox. For requests like 'read my last email', 'check my latest email', or 'my emails': "
                        "(1) Call this tool directly with max_results=1 (or as needed by user intent) without asking pre-check confirmation questions. "
                        "(2) Assume the connected Gmail account and inbox by default. "
                        "(3) Ask a follow-up only when needed after the attempt: authentication failed, result is empty, or user explicitly requested specific account/query. "
                        "(4) When successful, return results immediately with optional follow-up suggestion."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of emails to retrieve (default: 10)",
                            },
                            "query": {
                                "type": "string",
                                "description": "Gmail search query (e.g., 'from:sender@example.com')",
                            },
                        },
                        "required": [],
                    },
                },
                {
                    "name": "send_email",
                    "description": (
                        "Send an email via Gmail. When user wants to send mail: "
                        "(1) Call this directly with required fields (to, subject, body). "
                        "(2) Ask for missing required fields before attempting. "
                        "(3) Optional cc/bcc can be inferred from user context or asked if ambiguous. "
                        "(4) Report result (sent or failed) immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address"},
                            "subject": {"type": "string", "description": "Email subject"},
                            "body": {"type": "string", "description": "Email body (plain text or HTML)"},
                            "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
                            "bcc": {"type": "string", "description": "BCC recipients (comma-separated)"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
                {
                    "name": "get_email",
                    "description": (
                        "Get details of a specific email by ID. When user references a specific email: "
                        "(1) Extract or ask for the email_id (usually from prior read_emails call). "
                        "(2) Call this directly once email_id is known. "
                        "(3) Return full message details immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "email_id": {
                                "type": "string",
                                "description": "Gmail message ID",
                            }
                        },
                        "required": ["email_id"],
                    },
                },
                {
                    "name": "calendar_list_events",
                    "description": (
                        "List upcoming Google Calendar events. For read-only requests like 'my google calendar', 'list my calendar events', 'what's on my calendar', or 'check tomorrow': "
                        "(1) Call this directly without asking pre-check consent or option menus. "
                        "(2) Default to calendar_id='primary' when user did not specify one. "
                        "(3) If user says 'tomorrow', compute time_min/time_max for tomorrow in their timezone when known. "
                        "(4) If no date provided, list upcoming events. "
                        "(5) Ask follow-up only after failed attempt if: auth/credentials missing/invalid, calendar access denied, or truly ambiguous timezone. "
                        "(6) When successful, return results immediately in concise form. "
                        "Note: Use timezone from user profile (IANA format: e.g., America/Toronto) when available."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of events to retrieve (default: 10)",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Google Calendar ID (default: primary)",
                            },
                            "time_min": {
                                "type": "string",
                                "description": "RFC3339 lower time bound (default: now)",
                            },
                            "time_max": {
                                "type": "string",
                                "description": "RFC3339 upper time bound",
                            },
                            "query": {
                                "type": "string",
                                "description": "Free-text search query for events",
                            },
                        },
                        "required": [],
                    },
                },
                {
                    "name": "calendar_create_event",
                    "description": (
                        "Create a Google Calendar event. When user wants to schedule: "
                        "(1) Require all fields: summary, start_time, end_time, timezone, attendees ([] if none). "
                        "(2) Do NOT invent defaults for times or timezone. "
                        "(3) Ask explicitly for missing required fields with examples. "
                        "(4) Return success/failure and event details."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string", "description": "Event title"},
                            "start_time": {
                                "type": "string",
                                "description": "RFC3339 event start date-time",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "RFC3339 event end date-time",
                            },
                            "timezone": {
                                "type": "string",
                                "description": "IANA timezone name (Google Calendar format, e.g.: America/Toronto). Use user profile timezone when available.",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Google Calendar ID (default: primary)",
                            },
                            "attendees": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of attendee emails. Use [] if no attendees.",
                            },
                            "description": {"type": "string", "description": "Event description"},
                            "location": {"type": "string", "description": "Event location"},
                        },
                        "required": ["summary", "start_time", "end_time", "timezone", "attendees"],
                    },
                },
                {
                    "name": "calendar_get_event",
                    "description": (
                        "Get details of a specific Google Calendar event. When user references a specific event: "
                        "(1) Extract or ask for the event_id (from prior list_events or user input). "
                        "(2) Call this directly once event_id is known. "
                        "(3) Default to primary calendar if not specified. "
                        "(4) Return full event details immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "event_id": {
                                "type": "string",
                                "description": "Google Calendar event ID",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Google Calendar ID (default: primary)",
                            },
                        },
                        "required": ["event_id"],
                    },
                },
                {
                    "name": "calendar_update_event",
                    "description": (
                        "Update fields of an existing Google Calendar event. When user wants to modify an event: "
                        "(1) Require event_id (ask for it if not known). "
                        "(2) Ask which fields to update (summary, start_time, end_time, timezone, attendees, description, location). "
                        "(3) Call this only with the fields user explicitly wants to change. "
                        "(4) Return confirmation of changes."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "event_id": {
                                "type": "string",
                                "description": "Google Calendar event ID",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Google Calendar ID (default: primary)",
                            },
                            "summary": {"type": "string", "description": "Updated event title"},
                            "start_time": {
                                "type": "string",
                                "description": "Updated RFC3339 event start date-time",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "Updated RFC3339 event end date-time",
                            },
                            "timezone": {
                                "type": "string",
                                "description": "IANA timezone name (Google Calendar format, e.g.: America/Toronto). Use user profile timezone when available.",
                            },
                            "attendees": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Updated attendee email list. Use [] to clear attendees.",
                            },
                            "description": {"type": "string", "description": "Updated event description"},
                            "location": {"type": "string", "description": "Updated event location"},
                        },
                        "required": ["event_id"],
                    },
                },
                {
                    "name": "calendar_delete_event",
                    "description": (
                        "Delete a Google Calendar event. When user wants to remove an event: "
                        "(1) Ask for explicit confirmation before deleting (destructive action). "
                        "(2) Require event_id. "
                        "(3) Call this only after user confirms. "
                        "(4) Report deletion success/failure."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "event_id": {
                                "type": "string",
                                "description": "Google Calendar event ID",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Google Calendar ID (default: primary)",
                            },
                        },
                        "required": ["event_id"],
                    },
                },
                {
                    "name": "notion_list_children",
                    "description": (
                        "List child pages/databases under the configured parent page. For read requests like 'show my Notion pages': "
                        "(1) Call this directly; respects configured parent page automatically. "
                        "(2) Use max_results to limit output (default: 10). "
                        "(3) Return list of child items immediately. "
                        "(4) Ask follow-up only if Notion access fails."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of items to retrieve (default: 10)",
                            }
                        },
                        "required": [],
                    },
                },
                {
                    "name": "notion_create_page",
                    "description": (
                        "Create a new Notion page under the configured parent page. When user wants to add a page: "
                        "(1) Require title (ask if missing). "
                        "(2) Optional content can be added or left empty. "
                        "(3) Call this directly once title is provided. "
                        "(4) Return the new page ID and confirmation."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Page title"},
                            "content": {"type": "string", "description": "Optional page content"},
                        },
                        "required": ["title"],
                    },
                },
                {
                    "name": "notion_append_to_page",
                    "description": (
                        "Append a paragraph to an existing Notion page. When user wants to add content to a page: "
                        "(1) Require page_id (extract from prior list or ask user). "
                        "(2) Require content to append. "
                        "(3) Call this directly once both are provided. "
                        "(4) Report success/failure."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Notion page ID"},
                            "content": {"type": "string", "description": "Content to append"},
                        },
                        "required": ["page_id", "content"],
                    },
                },
                {
                    "name": "notion_get_page",
                    "description": (
                        "Get details for a Notion page. When user references a specific page: "
                        "(1) Require page_id (extract from prior list or ask for it). "
                        "(2) Call this directly once page_id is known. "
                        "(3) Return full page content and metadata immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Notion page ID"},
                        },
                        "required": ["page_id"],
                    },
                },
                {
                    "name": "weather_get_current",
                    "description": (
                        "Get current weather for a location. Default for generic weather requests. "
                        "Use unit=celsius unless user asks for Fahrenheit. If lookup fails, retry once with a more explicit "
                        "location string (for example include full region/country) before asking the user."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": (
                                    "City or place name. Prefer explicit locations when needed "
                                    "(e.g., 'Hamilton, Ontario, Canada' instead of ambiguous abbreviations)."
                                ),
                            },
                            "unit": {
                                "type": "string",
                                "description": "Temperature unit: celsius or fahrenheit (default: celsius)",
                            },
                        },
                        "required": ["location"],
                    },
                },
                {
                    "name": "weather_get_forecast",
                    "description": (
                        "Get weather forecast for a location when user asks for upcoming days/range. "
                        "If location lookup fails, retry once with a more explicit location string before follow-up questions."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": (
                                    "City or place name. Prefer explicit locations when needed "
                                    "(e.g., 'Hamilton, Ontario, Canada')."
                                ),
                            },
                            "days": {
                                "type": "integer",
                                "description": "Number of forecast days (1-7, default: 3)",
                            },
                            "unit": {
                                "type": "string",
                                "description": "Temperature unit: celsius or fahrenheit (default: celsius)",
                            },
                        },
                        "required": ["location"],
                    },
                },
                {
                    "name": "obsidian_list_vaults",
                    "description": (
                        "List discovered Obsidian vaults. For vault discovery requests: "
                        "(1) Call this directly; no parameters needed. "
                        "(2) Returns all available vaults automatically discovered. "
                        "(3) Use vault names or paths from result for other vault operations."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
                {
                    "name": "obsidian_list_notes",
                    "description": (
                        "List markdown notes in an Obsidian vault. For read requests like 'list my notes' or 'show vault contents': "
                        "(1) Call this directly; can auto-detect vault if only one exists. "
                        "(2) Specify vault_name or vault_path if user has multiple vaults. "
                        "(3) Use max_results to limit output (default: 200). "
                        "(4) Return list of note paths immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "vault_name": {
                                "type": "string",
                                "description": "Discovered vault name",
                            },
                            "vault_path": {
                                "type": "string",
                                "description": "Absolute vault path override",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of notes to return (default: 200)",
                            },
                        },
                        "required": [],
                    },
                },
                {
                    "name": "obsidian_read_note",
                    "description": (
                        "Read a note from an Obsidian vault. When user wants to read a specific note: "
                        "(1) Call this directly with note_path (from prior list_notes or user input). "
                        "(2) Auto-detect vault if only one exists; specify vault_name/vault_path if ambiguous. "
                        "(3) Return full note content immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "vault_name": {
                                "type": "string",
                                "description": "Discovered vault name",
                            },
                            "vault_path": {
                                "type": "string",
                                "description": "Absolute vault path override",
                            },
                            "note_path": {
                                "type": "string",
                                "description": "Path to the note within the vault",
                            },
                        },
                        "required": ["note_path"],
                    },
                },
                {
                    "name": "obsidian_create_note",
                    "description": (
                        "Create a note in an Obsidian vault. When user wants to create a new note: "
                        "(1) Require note_path and content. "
                        "(2) Auto-detect vault if only one exists; ask user to specify if ambiguous. "
                        "(3) By default, do NOT overwrite existing notes (set overwrite=false). "
                        "(4) Ask before overwriting if note_path already exists. "
                        "(5) Return creation success/failure."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "vault_name": {
                                "type": "string",
                                "description": "Discovered vault name",
                            },
                            "vault_path": {
                                "type": "string",
                                "description": "Absolute vault path override",
                            },
                            "note_path": {
                                "type": "string",
                                "description": "Path to the note within the vault",
                            },
                            "content": {
                                "type": "string",
                                "description": "Markdown content to write",
                            },
                            "overwrite": {
                                "type": "boolean",
                                "description": "Overwrite if note already exists (default: false)",
                            },
                        },
                        "required": ["note_path", "content"],
                    },
                },
                {
                    "name": "obsidian_update_note",
                    "description": (
                        "Update or append to an existing Obsidian note. When user wants to modify a note: "
                        "(1) Require note_path and content. "
                        "(2) Default append=false (replace content); set append=true only if user explicitly asks to add to the end. "
                        "(3) Auto-detect vault if only one exists; ask user to specify if ambiguous. "
                        "(4) Return update success/failure."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "vault_name": {
                                "type": "string",
                                "description": "Discovered vault name",
                            },
                            "vault_path": {
                                "type": "string",
                                "description": "Absolute vault path override",
                            },
                            "note_path": {
                                "type": "string",
                                "description": "Path to the note within the vault",
                            },
                            "content": {
                                "type": "string",
                                "description": "Markdown content to write",
                            },
                            "append": {
                                "type": "boolean",
                                "description": "Append content instead of replacing (default: false)",
                            },
                        },
                        "required": ["note_path", "content"],
                    },
                },
                {
                    "name": "obsidian_search_notes",
                    "description": (
                        "Search notes in an Obsidian vault. For search requests like 'find notes about X': "
                        "(1) Require search query. "
                        "(2) Auto-detect vault if only one exists; ask user to specify if ambiguous. "
                        "(3) Use max_results to limit matches (default: 25). "
                        "(4) Return matching note paths immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "vault_name": {
                                "type": "string",
                                "description": "Discovered vault name",
                            },
                            "vault_path": {
                                "type": "string",
                                "description": "Absolute vault path override",
                            },
                            "query": {
                                "type": "string",
                                "description": "Search text",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of matches to return (default: 25)",
                            },
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "obsidian_get_note_metadata",
                    "description": (
                        "Get metadata and frontmatter for an Obsidian note. When user wants metadata/frontmatter: "
                        "(1) Require note_path. "
                        "(2) Auto-detect vault if only one exists; ask user to specify if ambiguous. "
                        "(3) Call this directly once note_path is known. "
                        "(4) Return metadata and frontmatter immediately."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "vault_name": {
                                "type": "string",
                                "description": "Discovered vault name",
                            },
                            "vault_path": {
                                "type": "string",
                                "description": "Absolute vault path override",
                            },
                            "note_path": {
                                "type": "string",
                                "description": "Path to the note within the vault",
                            },
                        },
                        "required": ["note_path"],
                    },
                },
            ]
        }

    async def handle_call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        try:
            if name == "read_emails":
                max_results = arguments.get("max_results", 10)
                query = arguments.get("query", "")
                result = await self._get_gmail().read_emails(max_results, query)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "send_email":
                to = arguments.get("to")
                subject = arguments.get("subject")
                body = arguments.get("body")
                cc = arguments.get("cc")
                bcc = arguments.get("bcc")
                result = await self._get_gmail().send_email(to, subject, body, cc, bcc)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "get_email":
                email_id = arguments.get("email_id")
                result = await self._get_gmail().get_email(email_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "calendar_list_events":
                max_results = arguments.get("max_results", 10)
                calendar_id = arguments.get("calendar_id", "primary")
                time_min = arguments.get("time_min")
                time_max = arguments.get("time_max")
                query = arguments.get("query", "")
                result = await self._get_calendar().list_events(
                    max_results=max_results,
                    calendar_id=calendar_id,
                    time_min=time_min,
                    time_max=time_max,
                    query=query,
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "calendar_create_event":
                required_fields = ["summary", "start_time", "end_time", "timezone", "attendees"]
                missing_fields = []
                for field in required_fields:
                    value = arguments.get(field)
                    if value is None:
                        missing_fields.append(field)
                    elif isinstance(value, str) and not value.strip():
                        missing_fields.append(field)

                attendees = arguments.get("attendees")
                invalid_fields = []
                if attendees is not None and not isinstance(attendees, list):
                    invalid_fields.append("attendees")

                if missing_fields or invalid_fields:
                    clarification = self._calendar_clarification_response(
                        missing_fields=missing_fields,
                        invalid_fields=invalid_fields,
                    )
                    return {"content": [{"type": "text", "text": json.dumps(clarification)}]}

                summary = arguments.get("summary")
                start_time = arguments.get("start_time")
                end_time = arguments.get("end_time")
                timezone_name = arguments.get("timezone")
                calendar_id = arguments.get("calendar_id", "primary")
                description = arguments.get("description")
                location = arguments.get("location")
                result = await self._get_calendar().create_event(
                    summary=summary,
                    start_time=start_time,
                    end_time=end_time,
                    timezone_name=timezone_name,
                    calendar_id=calendar_id,
                    attendees=attendees,
                    description=description,
                    location=location,
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "calendar_get_event":
                event_id = arguments.get("event_id")
                calendar_id = arguments.get("calendar_id", "primary")
                result = await self._get_calendar().get_event(event_id=event_id, calendar_id=calendar_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "calendar_update_event":
                event_id = arguments.get("event_id")
                if not event_id:
                    clarification = {
                        "needs_clarification": True,
                        "missing_fields": ["event_id"],
                        "message": "Please provide the event_id to update.",
                    }
                    return {"content": [{"type": "text", "text": json.dumps(clarification)}]}

                updatable_fields = [
                    "summary",
                    "start_time",
                    "end_time",
                    "timezone",
                    "attendees",
                    "description",
                    "location",
                ]
                has_any_updates = any(field in arguments for field in updatable_fields)
                if not has_any_updates:
                    clarification = {
                        "needs_clarification": True,
                        "message": (
                            "Please specify what to update (for example summary, time, "
                            "timezone, attendees, description, or location)."
                        ),
                    }
                    return {"content": [{"type": "text", "text": json.dumps(clarification)}]}

                attendees = arguments.get("attendees")
                if attendees is not None and not isinstance(attendees, list):
                    clarification = {
                        "needs_clarification": True,
                        "invalid_fields": ["attendees"],
                        "message": "attendees must be a list of emails, or [] to clear attendees.",
                    }
                    return {"content": [{"type": "text", "text": json.dumps(clarification)}]}

                calendar_id = arguments.get("calendar_id", "primary")
                result = await self._get_calendar().update_event(
                    event_id=event_id,
                    calendar_id=calendar_id,
                    summary=arguments.get("summary"),
                    start_time=arguments.get("start_time"),
                    end_time=arguments.get("end_time"),
                    timezone_name=arguments.get("timezone"),
                    attendees=attendees,
                    description=arguments.get("description"),
                    location=arguments.get("location"),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "calendar_delete_event":
                event_id = arguments.get("event_id")
                if not event_id:
                    clarification = {
                        "needs_clarification": True,
                        "missing_fields": ["event_id"],
                        "message": "Please provide the event_id to delete.",
                    }
                    return {"content": [{"type": "text", "text": json.dumps(clarification)}]}

                calendar_id = arguments.get("calendar_id", "primary")
                result = await self._get_calendar().delete_event(event_id=event_id, calendar_id=calendar_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_list_children":
                max_results = arguments.get("max_results", 10)
                result = await self._get_notion().list_children(max_results)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_create_page":
                title = arguments.get("title")
                content = arguments.get("content")
                result = await self._get_notion().create_page(title, content)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_append_to_page":
                page_id = arguments.get("page_id")
                content = arguments.get("content")
                result = await self._get_notion().append_to_page(page_id, content)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_get_page":
                page_id = arguments.get("page_id")
                result = await self._get_notion().get_page(page_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "weather_get_current":
                location = arguments.get("location")
                unit = arguments.get("unit", "celsius")
                result = await self._get_weather().get_current_weather(location, unit)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "weather_get_forecast":
                location = arguments.get("location")
                days = arguments.get("days", 3)
                unit = arguments.get("unit", "celsius")
                result = await self._get_weather().get_forecast(location, days, unit)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "obsidian_list_vaults":
                result = await self._get_obsidian().list_vaults()
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "obsidian_list_notes":
                result = await self._get_obsidian().list_notes(
                    vault_name=arguments.get("vault_name"),
                    vault_path=arguments.get("vault_path"),
                    max_results=arguments.get("max_results", 200),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "obsidian_read_note":
                result = await self._get_obsidian().read_note(
                    note_path=arguments.get("note_path", ""),
                    vault_name=arguments.get("vault_name"),
                    vault_path=arguments.get("vault_path"),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "obsidian_create_note":
                result = await self._get_obsidian().create_note(
                    note_path=arguments.get("note_path", ""),
                    content=arguments.get("content", ""),
                    vault_name=arguments.get("vault_name"),
                    vault_path=arguments.get("vault_path"),
                    overwrite=arguments.get("overwrite", False),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "obsidian_update_note":
                result = await self._get_obsidian().update_note(
                    note_path=arguments.get("note_path", ""),
                    content=arguments.get("content", ""),
                    vault_name=arguments.get("vault_name"),
                    vault_path=arguments.get("vault_path"),
                    append=arguments.get("append", False),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "obsidian_search_notes":
                result = await self._get_obsidian().search_notes(
                    query=arguments.get("query", ""),
                    vault_name=arguments.get("vault_name"),
                    vault_path=arguments.get("vault_path"),
                    max_results=arguments.get("max_results", 25),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "obsidian_get_note_metadata":
                result = await self._get_obsidian().get_note_metadata(
                    note_path=arguments.get("note_path", ""),
                    vault_name=arguments.get("vault_name"),
                    vault_path=arguments.get("vault_path"),
                )
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

        except Exception as e:
            logger.error("combined_tool_error", tool=name, error=str(e))
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    async def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process an incoming JSON-RPC message."""
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
                    params.get("name"), params.get("arguments", {})
                )
            elif method == "notifications/initialized":
                return None
            else:
                result = {"error": f"Unknown method: {method}"}

            if msg_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result,
                }
        except Exception as e:
            logger.error("message_processing_error", error=str(e))
            if msg_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}",
                    },
                }
        return None

    def run(self) -> None:
        """Run the MCP server (synchronous version for stdio)."""
        logger.info("combined_mcp_server_started")

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
                    logger.error("server_error", error=str(e))

        except KeyboardInterrupt:
            logger.info("combined_mcp_server_stopped")
        except Exception as e:
            logger.error("combined_mcp_fatal_error", error=str(e))
            sys.exit(1)


if __name__ == "__main__":
    server = CombinedMCPServer()
    server.run()
