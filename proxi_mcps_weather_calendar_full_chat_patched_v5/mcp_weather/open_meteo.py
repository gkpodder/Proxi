
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import requests
from datetime import datetime, timezone

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

@dataclass
class GeoResult:
    name: str
    country: str
    admin1: Optional[str]
    latitude: float
    longitude: float
    timezone: str

def geocode(place: str, count: int = 5) -> List[GeoResult]:
    params = {"name": place, "count": count, "language": "en", "format": "json"}
    r = requests.get(GEOCODE_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    out: List[GeoResult] = []
    for item in data.get("results", [])[:count]:
        out.append(GeoResult(
            name=item.get("name", place),
            country=item.get("country", ""),
            admin1=item.get("admin1"),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            timezone=item.get("timezone", "auto"),
        ))
    return out

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def current_weather(lat: float, lon: float, tz: str = "auto") -> Dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "current": [
            "temperature_2m",
            "apparent_temperature",
            "wind_speed_10m",
            "wind_direction_10m",
            "relative_humidity_2m",
            "precipitation",
        ],
    }
    r = requests.get(FORECAST_URL, params=params, timeout=20)
    r.raise_for_status()
    j = r.json()
    return {"fetched_at": _now_iso(), "timezone": j.get("timezone", tz), "current": j.get("current", {}) or {}, "units": j.get("current_units", {}) or {}}

def forecast_daily(lat: float, lon: float, days: int = 7, tz: str = "auto") -> Dict[str, Any]:
    days = max(1, min(int(days), 16))
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "forecast_days": days,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "snowfall_sum",
            "wind_speed_10m_max",
            "uv_index_max",
        ],
    }
    r = requests.get(FORECAST_URL, params=params, timeout=20)
    r.raise_for_status()
    j = r.json()
    return {"fetched_at": _now_iso(), "timezone": j.get("timezone", tz), "daily": j.get("daily", {}) or {}, "units": j.get("daily_units", {}) or {}}

def forecast_hourly(lat: float, lon: float, hours: int = 24, tz: str = "auto") -> Dict[str, Any]:
    hours = max(1, min(int(hours), 168))
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "hourly": [
            "temperature_2m",
            "apparent_temperature",
            "precipitation",
            "snowfall",
            "rain",
            "wind_speed_10m",
            "wind_gusts_10m",
            "cloud_cover",
            "visibility",
        ],
    }
    r = requests.get(FORECAST_URL, params=params, timeout=20)
    r.raise_for_status()
    j = r.json()
    hourly = j.get("hourly", {}) or {}
    if "time" in hourly and isinstance(hourly["time"], list) and len(hourly["time"]) > hours:
        hourly = {k: (v[:hours] if isinstance(v, list) else v) for k, v in hourly.items()}
    return {"fetched_at": _now_iso(), "timezone": j.get("timezone", tz), "hourly": hourly, "units": j.get("hourly_units", {}) or {}}
