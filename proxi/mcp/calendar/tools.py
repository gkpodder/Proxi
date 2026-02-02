import asyncio
import json
from typing import Any, Dict

from proxi.tools.base import BaseTool, ToolResult
from proxi.mcp.calendar import calendar_app as cal

def _to_tool_result(res: Dict[str, Any]) -> ToolResult:
    ok = res.get("ok", False)
    
    # Convert all output to string
    output = ""
    if res.get("result"):
        output = str(res.get("result"))
    elif res.get("events"):
        output = json.dumps(res.get("events"), indent=2)
    elif res.get("calendars"):
        output = json.dumps(res.get("calendars"), indent=2)
    elif res.get("slots"):
        output = json.dumps(res.get("slots"), indent=2)
    
    return ToolResult(
        success=bool(ok),
        output=output or "success",
        error=res.get("stderr") if not ok else None,
        metadata={k: v for k, v in res.items() if k not in ("ok", "result", "events", "calendars", "slots", "stderr")},
    )

class CalendarOpenTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_open",
            description="Open the Calendar app",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(cal.open_calendar_app)
        return _to_tool_result(res)

class CalendarCloseTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_close",
            description="Close the Calendar app",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(cal.close_calendar_app)
        return _to_tool_result(res)

class CalendarListCalendarsTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_list_calendars",
            description="List available calendars",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(cal.list_calendars)
        return _to_tool_result(res)

class CalendarListTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_list_events",
            description="List all calendar events in a specific date/time range. Use this to find events by time window.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Start date/time in ISO format (YYYY-MM-DDTHH:MM:SS). Example: 2026-02-01T09:00:00"},
                    "date_to": {"type": "string", "description": "End date/time in ISO format (YYYY-MM-DDTHH:MM:SS). Example: 2026-02-01T22:00:00"},
                    "calendar_name": {"type": ["string", "null"], "description": "Optional calendar name to filter by"},
                },
                "required": ["date_from", "date_to"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(
            cal.list_events,
            arguments.get("date_from"),
            arguments.get("date_to"),
            arguments.get("calendar_name"),
        )
        return _to_tool_result(res)

class CalendarSearchTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_search_events",
            description="Search for events by title/name within a date range. Returns matching events.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Event title or keyword to search for"},
                    "date_from": {"type": "string", "description": "Start date/time in ISO format (YYYY-MM-DDTHH:MM:SS)"},
                    "date_to": {"type": "string", "description": "End date/time in ISO format (YYYY-MM-DDTHH:MM:SS)"},
                    "calendar_name": {"type": ["string", "null"], "description": "Optional calendar name"},
                },
                "required": ["query", "date_from", "date_to"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(
            cal.search_events,
            arguments.get("query"),
            arguments.get("date_from"),
            arguments.get("date_to"),
            arguments.get("calendar_name"),
        )
        return _to_tool_result(res)

class CalendarCreateTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_create_event",
            description="Create a new calendar event with ISO formatted dates",
            parameters_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "start": {"type": "string", "description": "Start date/time in ISO format (YYYY-MM-DDTHH:MM:SS)"},
                    "end": {"type": "string", "description": "End date/time in ISO format (YYYY-MM-DDTHH:MM:SS), must be after start"},
                    "location": {"type": ["string", "null"], "description": "Event location"},
                    "notes": {"type": ["string", "null"], "description": "Event notes/description"},
                    "calendar_name": {"type": ["string", "null"], "description": "Target calendar (e.g., 'Work', 'Personal')"},
                },
                "required": ["title", "start", "end"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(
            cal.create_event,
            arguments.get("title"),
            arguments.get("start"),
            arguments.get("end"),
            arguments.get("location"),
            arguments.get("notes"),
            arguments.get("calendar_name"),
        )
        return _to_tool_result(res)

class CalendarUpdateTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_update_event",
            description="Update a calendar event",
            parameters_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID to update"},
                    "title": {"type": ["string", "null"], "description": "New event title"},
                    "start": {"type": ["string", "null"], "description": "New start date/time in ISO format"},
                    "end": {"type": ["string", "null"], "description": "New end date/time in ISO format"},
                    "location": {"type": ["string", "null"], "description": "New location"},
                    "notes": {"type": ["string", "null"], "description": "New notes"},
                },
                "required": ["event_id"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(
            cal.update_event,
            arguments.get("event_id"),
            arguments.get("title"),
            arguments.get("start"),
            arguments.get("end"),
            arguments.get("location"),
            arguments.get("notes"),
        )
        return _to_tool_result(res)

class CalendarDeleteTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_delete_event",
            description="Delete a calendar event",
            parameters_schema={
                "type": "object",
                "properties": {"event_id": {"type": "string", "description": "Event ID to delete"}},
                "required": ["event_id"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(cal.delete_event, arguments.get("event_id"))
        return _to_tool_result(res)

class CalendarFreeSlotsTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calendar_free_slots",
            description="Find free time slots on a specific date",
            parameters_schema={
                "type": "object",
                "properties": {
                    "date_ymd": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "duration_minutes": {"type": "integer", "description": "Desired slot duration in minutes"},
                    "work_start": {"type": "string", "description": "Work day start time (HH:MM:SS)"},
                    "work_end": {"type": "string", "description": "Work day end time (HH:MM:SS)"},
                },
                "required": ["date_ymd"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        res = await asyncio.to_thread(
            cal.find_free_slots,
            arguments.get("date_ymd"),
            arguments.get("duration_minutes", 30),
            arguments.get("work_start", "09:00:00"),
            arguments.get("work_end", "17:00:00"),
        )
        return _to_tool_result(res)

def register_calendar_tools(registry):
    registry.register(CalendarOpenTool())
    registry.register(CalendarCloseTool())
    registry.register(CalendarListCalendarsTool())
    registry.register(CalendarListTool())
    registry.register(CalendarSearchTool())
    registry.register(CalendarCreateTool())
    registry.register(CalendarUpdateTool())
    registry.register(CalendarDeleteTool())
    registry.register(CalendarFreeSlotsTool())