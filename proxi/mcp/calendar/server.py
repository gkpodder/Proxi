from __future__ import annotations
from fastmcp import FastMCP
from . import calendar_app as cal

mcp = FastMCP("calendar")

@mcp.tool()
def calendar_open():
    return cal.open_calendar_app()

@mcp.tool()
def calendar_close():
    return cal.close_calendar_app()

@mcp.tool()
def calendar_list_calendars():
    return cal.list_calendars()

@mcp.tool()
def calendar_list_events(date_from: str, date_to: str, calendar_name: str | None = None):
    return cal.list_events(date_from, date_to, calendar_name)

@mcp.tool()
def calendar_search_events(query: str, date_from: str, date_to: str, calendar_name: str | None = None):
    return cal.search_events(query, date_from, date_to, calendar_name)

@mcp.tool()
def calendar_create_event(title: str, start: str, end: str, location: str | None = None, notes: str | None = None, calendar_name: str | None = None):
    return cal.create_event(title, start, end, location, notes, calendar_name)

@mcp.tool()
def calendar_update_event(event_id: str, title: str | None = None, start: str | None = None, end: str | None = None, location: str | None = None, notes: str | None = None):
    return cal.update_event(event_id, title, start, end, location, notes)

@mcp.tool()
def calendar_delete_event(event_id: str):
    return cal.delete_event(event_id)

@mcp.tool()
def calendar_free_slots(date_ymd: str, duration_minutes: int = 30, work_start: str = "09:00:00", work_end: str = "17:00:00"):
    return cal.find_free_slots(date_ymd, duration_minutes, work_start, work_end)

if __name__ == "__main__":
    mcp.run()
