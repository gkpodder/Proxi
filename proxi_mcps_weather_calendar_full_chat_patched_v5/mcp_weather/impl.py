
from __future__ import annotations
from typing import Dict, Any, Optional

from .state import load_state, add_location, remove_location, set_home, set_units
from .open_meteo import geocode, current_weather, forecast_daily, forecast_hourly
from .risk import risk_at, best_time_in_window
from .weather_app import open_weather_app, show_location, add_city_ui, remove_city_ui

def _best_geo(place: str) -> Dict[str, Any]:
    res = geocode(place, count=1)
    if not res:
        raise ValueError(f"Could not geocode: {place}")
    return res[0].__dict__

# state
def list_locations_impl() -> Dict[str, Any]:
    return {"ok": True, "state": load_state()}

def add_location_impl(place: str, also_open_app: bool = True) -> Dict[str, Any]:
    st = add_location(place)
    ui = add_city_ui(place) if also_open_app else None
    return {"ok": True, "state": st, "ui": ui}

def remove_location_impl(place: str, also_open_app: bool = True) -> Dict[str, Any]:
    st = remove_location(place)
    ui = remove_city_ui(place) if also_open_app else None
    return {"ok": True, "state": st, "ui": ui}

def set_home_location_impl(place: str) -> Dict[str, Any]:
    st = set_home(place)
    return {"ok": True, "state": st}

def set_units_impl(units: str) -> Dict[str, Any]:
    st = set_units(units)
    return {"ok": True, "state": st}

# data
def current_impl(place: Optional[str] = None) -> Dict[str, Any]:
    st = load_state()
    p = (place or st.get("home_location") or (st.get("saved_locations") or [None])[0])
    if not p:
        return {"ok": False, "error": "No place provided and no home/saved location set"}
    g = _best_geo(p)
    data = current_weather(g["latitude"], g["longitude"], g.get("timezone","auto"))
    return {"ok": True, "place": p, "geo": g, **data, "prefs": {"units": st.get("units","C")}}

def daily_impl(place: str, days: int = 7) -> Dict[str, Any]:
    g = _best_geo(place)
    data = forecast_daily(g["latitude"], g["longitude"], days=days, tz=g.get("timezone","auto"))
    return {"ok": True, "place": place, "geo": g, **data}

def hourly_impl(place: str, hours: int = 24) -> Dict[str, Any]:
    g = _best_geo(place)
    data = forecast_hourly(g["latitude"], g["longitude"], hours=hours, tz=g.get("timezone","auto"))
    return {"ok": True, "place": place, "geo": g, **data}

# intelligence
def risk_impl(place: str, iso_datetime: str, activity: str = "driving") -> Dict[str, Any]:
    g = _best_geo(place)
    h = forecast_hourly(g["latitude"], g["longitude"], hours=168, tz=g.get("timezone","auto"))
    r = risk_at(h["hourly"], iso_datetime, activity)
    return {"ok": True, "place": place, "geo": g, "risk": r}

def best_time_impl(place: str, activity: str, start_dt: str, end_dt: str, step_minutes: int = 60) -> Dict[str, Any]:
    g = _best_geo(place)
    h = forecast_hourly(g["latitude"], g["longitude"], hours=168, tz=g.get("timezone","auto"))
    b = best_time_in_window(h["hourly"], start_dt, end_dt, activity=activity, step_minutes=step_minutes)
    return {"ok": True, "place": place, "geo": g, "best_time": b}

def alerts_impl(place: str, start_dt: str, end_dt: str, snow_threshold: float=1.0, rain_threshold: float=5.0, gust_threshold: float=40.0, visibility_threshold: float=1000.0) -> Dict[str, Any]:
    from datetime import datetime
    g = _best_geo(place)
    h = forecast_hourly(g["latitude"], g["longitude"], hours=168, tz=g.get("timezone","auto"))
    hourly = h["hourly"]; times = hourly.get("time", []) or []
    def parse(x: str) -> datetime:
        try: return datetime.fromisoformat(x.replace("Z","+00:00")).replace(tzinfo=None)
        except Exception:
            try: return datetime.fromisoformat(x)
            except Exception: return datetime.min
    start = parse(start_dt); end = parse(end_dt)

    def col(key, default):
        arr = hourly.get(key)
        if isinstance(arr, list) and len(arr)==len(times): return arr
        return [default]*len(times)

    snowfall = col("snowfall", 0.0); rain = col("rain", 0.0); gusts = col("wind_gusts_10m", 0.0); vis = col("visibility", 99999.0)
    alerts = []
    for i, t in enumerate(times):
        dt = parse(t)
        if dt < start or dt > end: 
            continue
        if float(snowfall[i] or 0) >= snow_threshold:
            alerts.append({"time": t, "type": "snow", "value": float(snowfall[i]), "threshold": snow_threshold})
        if float(rain[i] or 0) >= rain_threshold:
            alerts.append({"time": t, "type": "rain", "value": float(rain[i]), "threshold": rain_threshold})
        if float(gusts[i] or 0) >= gust_threshold:
            alerts.append({"time": t, "type": "gusts", "value": float(gusts[i]), "threshold": gust_threshold})
        if float(vis[i] or 99999) <= visibility_threshold:
            alerts.append({"time": t, "type": "visibility", "value": float(vis[i]), "threshold": visibility_threshold})

    return {"ok": True, "place": place, "geo": g, "alerts": alerts, "window": {"start": start_dt, "end": end_dt}}

# UI
def open_weather_app_impl() -> Dict[str, Any]:
    return open_weather_app()

def show_in_weather_app_impl(place: str) -> Dict[str, Any]:
    return show_location(place)
