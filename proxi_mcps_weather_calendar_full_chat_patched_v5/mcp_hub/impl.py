
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from mcp_weather.impl import risk_impl, best_time_impl
from Capstone.proxi.mcp.calendar.impl import create_event_impl, update_event_impl

def schedule_drive_if_safe_impl(
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
    r = risk_impl(place, start_dt, activity)
    if not r.get("ok"):
        return r
    risk = (r.get("risk") or {}).get("risk", "unknown")

    acceptable = {"low": 0, "medium": 1, "high": 2}
    cur = acceptable.get(risk, 2)
    maxv = acceptable.get(max_risk, 0)

    def parse(s: str) -> datetime:
        try:
            return datetime.fromisoformat(s.replace("Z","+00:00")).replace(tzinfo=None)
        except Exception:
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return datetime.min

    start = parse(start_dt)
    if start == datetime.min:
        return {"ok": False, "error": "start_dt must be ISO or 'YYYY-MM-DD HH:MM:SS'"}
    end = start + timedelta(minutes=max(5,int(duration_minutes)))
    end_dt = end.isoformat(sep=" ")

    notes = []
    notes.append("Weather-aware scheduling:")
    notes.append(f"- Place checked: {place}")
    notes.append(f"- Risk at requested time: {risk}")
    for reason in (r.get("risk") or {}).get("reasons", [])[:6]:
        notes.append(f"- {reason}")
    notes.append(f"- Recommendation: {(r.get('risk') or {}).get('recommendation')}")

    suggested = None
    if cur > maxv:
        window_end = (start + timedelta(minutes=max(60,int(fallback_window_minutes)))).isoformat(sep=" ")
        best = best_time_impl(place, activity, start_dt, window_end, step_minutes=60)
        suggested = (best.get("best_time") or {}).get("best", {}).get("time_slot")
        notes.append(f"- Suggested safer time: {suggested}")

    created = create_event_impl(
        title=title,
        start=start_dt,
        end=end_dt,
        location=destination or place,
        notes="\n".join(notes),
        calendar_name=calendar_name
    )

    return {"ok": True, "requested_risk": r, "suggested_time": suggested, "calendar_event": created}

def reschedule_event_if_weather_bad_impl(
    event_id: str,
    place: str,
    start_dt: str,
    end_dt: str,
    activity: str = "driving",
    max_risk: str = "low",
    window_end_dt: Optional[str] = None,
) -> Dict[str, Any]:
    r = risk_impl(place, start_dt, activity)
    if not r.get("ok"):
        return r
    risk = (r.get("risk") or {}).get("risk", "unknown")
    acceptable = {"low": 0, "medium": 1, "high": 2}
    cur = acceptable.get(risk, 2)
    maxv = acceptable.get(max_risk, 0)
    if cur <= maxv:
        return {"ok": True, "note": "risk acceptable; no reschedule", "risk": r}

    if not window_end_dt:
        try:
            s = datetime.fromisoformat(start_dt.replace("Z","+00:00")).replace(tzinfo=None)
            window_end_dt = (s + timedelta(hours=4)).isoformat(sep=" ")
        except Exception:
            window_end_dt = start_dt

    best = best_time_impl(place, activity, start_dt, window_end_dt, step_minutes=60)
    suggested = (best.get("best_time") or {}).get("best", {}).get("time_slot")
    if not suggested:
        return {"ok": False, "error": "Could not find suggested time", "best": best}

    note = f"Rescheduled due to weather risk={risk}. Suggested new start={suggested}."
    upd = update_event_impl(event_id, notes=note, start=suggested)

    return {"ok": True, "risk": r, "best": best, "update": upd}
