from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List

from openai import OpenAI

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM = """You are Proxi's tool planner.
Your job: convert a user's natural language request into a minimal sequence of tool calls.

Return ONLY valid JSON (no markdown), matching this schema:

{
  "actions": [
    {
      "tool": "<tool_name>",
      "args": { ... }
    }
  ]
}

Available tools and args:

Weather tools:
- weather.open_weather_app: {}
- weather.show_in_weather_app: {"place": str}
- weather.list_locations: {}
- weather.add_location: {"place": str, "also_open_app": bool}
- weather.remove_location: {"place": str, "also_open_app": bool}
- weather.set_home_location: {"place": str}
- weather.set_units: {"units": "C"|"F"}
- weather.current: {"place": str|null}  # if null, use home/saved location
- weather.forecast_hourly: {"place": str, "hours": int}  # 1..168
- weather.forecast_daily: {"place": str, "days": int}    # 1..16
- weather.risk: {"place": str, "iso_datetime": str, "activity": "driving"|"outdoor"|"flight"}
- weather.best_time: {"place": str, "activity": str, "start_dt": str, "end_dt": str, "step_minutes": int}
- weather.alerts: {"place": str, "start_dt": str, "end_dt": str,
                   "snow_threshold": float, "rain_threshold": float, "gust_threshold": float, "visibility_threshold": float}

Calendar tools:
- calendar.open_calendar_app: {}
- calendar.close_calendar_app: {}
- calendar.list_calendars: {}
- calendar.upcoming: {"days": int, "calendar_name": str|null}
- calendar.list_events: {"date_from": str, "date_to": str, "calendar_name": str|null}
- calendar.search_events: {"query": str, "date_from": str, "date_to": str, "calendar_name": str|null}
- calendar.create_event: {"title": str, "start": str, "end": str, "location": str|null, "notes": str|null, "calendar_name": str|null}
- calendar.update_event: {"event_id": str, "title": str|null, "start": str|null, "end": str|null, "location": str|null, "notes": str|null}
- calendar.delete_event: {"event_id": str}
- calendar.free_slots: {"date_ymd": "YYYY-MM-DD", "duration_minutes": int, "work_start": "HH:MM:SS", "work_end": "HH:MM:SS"}

Hub tools (cross-talk):
- hub.schedule_drive_if_safe: {"place": str, "start_dt": str, "duration_minutes": int,
                               "title": str, "origin": str|null, "destination": str|null, "calendar_name": str|null,
                               "activity": str, "max_risk": "low"|"medium"|"high", "fallback_window_minutes": int}
- hub.reschedule_event_if_weather_bad: {"event_id": str, "place": str, "start_dt": str, "end_dt": str,
                                        "activity": str, "max_risk": "low"|"medium"|"high", "window_end_dt": str|null}

Rules:
- Use the fewest actions possible.
- If the user asks to delete/remove an event: FIRST search for it (calendar.search_events), THEN delete it (calendar.delete_event with the event_id from results).
- If the user asks to close/quit the calendar app: use calendar.close_calendar_app.
- If the user asks for weather in a place: use weather.current or weather.forecast_hourly/daily.
- If they say "in the Weather app" / "open the Weather app" / "show it in the app": include weather.open_weather_app and/or weather.show_in_weather_app.
- If they say "add/remove city in my Weather app": include weather.add_location/remove_location with also_open_app=true.
- If they ask to create/modify calendar events: use calendar.create_event/update_event/delete_event.
- If they ask to schedule based on weather (e.g., "if not snowing at 11, add a drive"): prefer hub.schedule_drive_if_safe.
- Date/time formatting: ALWAYS use "YYYY-MM-DD HH:MM:SS" (24h) unless the user already gives ISO; do best-effort conversion.
- If a date is ambiguous, choose the nearest reasonable future time.

Return JSON ONLY.

IMPORTANT: Interpret relative times like tonight/tomorrow/next week using the provided current local datetime.
"""

def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    # direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # try to find a JSON object in the text
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {"actions": [], "error": "Could not parse JSON from model output", "raw": text}

def plan(user_text: str) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"actions": [], "error": "OPENAI_API_KEY not set. Put it in .env or environment variables."}

    client = OpenAI(api_key=api_key)

    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    system = SYSTEM + f"\n\nCurrent local datetime is: {now_local}\n"

    resp = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        temperature=0.0,
        # if supported by the model, encourages strict JSON
        response_format={"type": "json_object"},
    )

    raw = (resp.choices[0].message.content or "").strip()
    return _extract_json(raw)
