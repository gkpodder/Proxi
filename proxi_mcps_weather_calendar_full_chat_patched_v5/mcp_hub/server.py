
from __future__ import annotations
from fastmcp import FastMCP
from typing import Dict, Any, Optional
from . import impl

mcp = FastMCP("mcp-proxi-hub")

@mcp.tool()
def schedule_drive_if_safe(
    place: str,
    start_dt: str,
    duration_minutes: int = 45,
    title: str = "Drive",
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    calendar_name: Optional[str] = None,
    activity: str = "driving",
    max_risk: str = "low",
    fallback_window_minutes: int = 240,
) -> Dict[str, Any]:
    return impl.schedule_drive_if_safe_impl(place, start_dt, duration_minutes, title, origin, destination, calendar_name, activity, max_risk, fallback_window_minutes)

@mcp.tool()
def reschedule_event_if_weather_bad(
    event_id: str,
    place: str,
    start_dt: str,
    end_dt: str,
    activity: str = "driving",
    max_risk: str = "low",
    window_end_dt: Optional[str] = None,
) -> Dict[str, Any]:
    return impl.reschedule_event_if_weather_bad_impl(event_id, place, start_dt, end_dt, activity, max_risk, window_end_dt)

if __name__ == "__main__":
    mcp.run()
