
from __future__ import annotations
from fastmcp import FastMCP
from typing import Dict, Any, Optional
from . import impl

mcp = FastMCP("mcp-weather-macos")

@mcp.tool()
def list_locations() -> Dict[str, Any]:
    return impl.list_locations_impl()

@mcp.tool()
def add_location(place: str, also_open_app: bool=True) -> Dict[str, Any]:
    return impl.add_location_impl(place, also_open_app)

@mcp.tool()
def remove_location(place: str, also_open_app: bool=True) -> Dict[str, Any]:
    return impl.remove_location_impl(place, also_open_app)

@mcp.tool()
def set_home_location(place: str) -> Dict[str, Any]:
    return impl.set_home_location_impl(place)

@mcp.tool()
def set_units(units: str) -> Dict[str, Any]:
    return impl.set_units_impl(units)

@mcp.tool()
def current(place: Optional[str]=None) -> Dict[str, Any]:
    return impl.current_impl(place)

@mcp.tool()
def forecast_daily(place: str, days: int=7) -> Dict[str, Any]:
    return impl.daily_impl(place, days)

@mcp.tool()
def forecast_hourly(place: str, hours: int=24) -> Dict[str, Any]:
    return impl.hourly_impl(place, hours)

@mcp.tool()
def risk(place: str, iso_datetime: str, activity: str="driving") -> Dict[str, Any]:
    return impl.risk_impl(place, iso_datetime, activity)

@mcp.tool()
def best_time(place: str, activity: str, start_dt: str, end_dt: str, step_minutes: int=60) -> Dict[str, Any]:
    return impl.best_time_impl(place, activity, start_dt, end_dt, step_minutes)

@mcp.tool()
def alerts(place: str, start_dt: str, end_dt: str, snow_threshold: float=1.0, rain_threshold: float=5.0, gust_threshold: float=40.0, visibility_threshold: float=1000.0) -> Dict[str, Any]:
    return impl.alerts_impl(place, start_dt, end_dt, snow_threshold, rain_threshold, gust_threshold, visibility_threshold)

@mcp.tool()
def open_weather_app() -> Dict[str, Any]:
    return impl.open_weather_app_impl()

@mcp.tool()
def show_in_weather_app(place: str) -> Dict[str, Any]:
    return impl.show_in_weather_app_impl(place)

if __name__ == "__main__":
    mcp.run()
