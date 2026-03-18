#!/usr/bin/env python3
"""Combined MCP Server for Gmail, Calendar, Notion, and Weather."""

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

from proxi.observability.logging import get_logger

if TYPE_CHECKING:
    from proxi.mcp.servers.calendar_tools import CalendarTools
    from proxi.mcp.servers.gmail_tools import GmailTools
    from proxi.mcp.servers.notion_tools import NotionTools
    from proxi.mcp.servers.weather_tools import WeatherTools

logger = get_logger(__name__)


class CombinedMCPServer:
    """MCP server for Gmail, Calendar, Notion, and Weather operations."""

    def __init__(self) -> None:
        """Initialize the combined MCP server."""
        self._gmail: "GmailTools | None" = None
        self._calendar: "CalendarTools | None" = None
        self._notion: "NotionTools | None" = None
        self._weather: "WeatherTools | None" = None

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
            "timezone": "What timezone should be used (IANA name, for example: America/Toronto)?",
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
                    "description": "Read emails from Gmail inbox",
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
                    "description": "Send an email via Gmail",
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
                    "description": "Get details of a specific email",
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
                    "description": "List upcoming Google Calendar events",
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
                        "Create a Google Calendar event. Do not invent defaults: "
                        "request explicit time, timezone, and attendees from the user if missing."
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
                                "description": "IANA timezone name (for example: America/Toronto)",
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
                    "description": "Get details of a specific Google Calendar event",
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
                    "description": "Update fields of an existing Google Calendar event",
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
                                "description": "IANA timezone name (for example: America/Toronto)",
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
                    "description": "Delete a Google Calendar event",
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
                    "description": "List child pages/databases under the configured parent page",
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
                    "description": "Create a new Notion page under the configured parent page",
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
                    "description": "Append a paragraph to an existing Notion page",
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
                    "description": "Get details for a Notion page",
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
                    "description": "Get current weather for a location",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City or place name (e.g., Toronto)",
                            },
                            "unit": {
                                "type": "string",
                                "description": "Temperature unit: celsius or fahrenheit",
                            },
                        },
                        "required": ["location"],
                    },
                },
                {
                    "name": "weather_get_forecast",
                    "description": "Get weather forecast for a location",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City or place name (e.g., Toronto)",
                            },
                            "days": {
                                "type": "integer",
                                "description": "Number of forecast days (1-7)",
                            },
                            "unit": {
                                "type": "string",
                                "description": "Temperature unit: celsius or fahrenheit",
                            },
                        },
                        "required": ["location"],
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
