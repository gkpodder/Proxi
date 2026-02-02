from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, Callable

from dotenv import load_dotenv

load_dotenv()

from shared.planner import plan

# Import impls (callable logic)
from mcp_weather import impl as weather
from Capstone.proxi.mcp.calendar import impl as calendar
from mcp_hub import impl as hub

ToolFn = Callable[..., Dict[str, Any]]

def _month_to_num(month: str) -> str:
    months = {"january": "01", "february": "02", "march": "03", "april": "04", 
              "may": "05", "june": "06", "july": "07", "august": "08",
              "september": "09", "october": "10", "november": "11", "december": "12"}
    return months.get(month.lower(), "01")

def _to_24h(h: int, m: int, ampm: str | None) -> tuple[int, int]:
    if ampm:
        a = ampm.lower()
        if a == "pm" and h != 12:
            h += 12
        if a == "am" and h == 12:
            h = 0
    return h, m

def _ok(x: Any) -> bool:
    return isinstance(x, dict) and x.get("ok") is True


def render_human(output: Dict[str, Any]) -> str:
    """Turn tool results into a human-friendly response for demos."""
    results = output.get("results", []) or []

    # If we didn’t execute anything, show what would happen
    if not results:
        planned = output.get("plan", {}) or {}
        actions = planned.get("actions", []) or []
        if actions:
            first = actions[0]
            return f"I’m ready to run: {first.get('tool')} with {first.get('args', {})}"
        return "I couldn't find any tool actions to run."

    # Prefer last successful result for summary
    last_ok = None
    for r in results:
        if isinstance(r, dict) and isinstance(r.get("result"), dict) and r["result"].get("ok") is True:
            last_ok = r

    def fmt_weather_current(res: Dict[str, Any]) -> str:
        cur = res.get("current", {}) or {}
        units = res.get("units", {}) or {}
        t = cur.get("temperature_2m")
        feels = cur.get("apparent_temperature")
        wind = cur.get("wind_speed_10m")
        hum = cur.get("relative_humidity_2m")
        precip = cur.get("precipitation")
        utemp = units.get("temperature_2m", "")
        uwind = units.get("wind_speed_10m", "")
        uprec = units.get("precipitation", "")
        place = res.get("place", "that location")
        bits = []
        if t is not None:
            bits.append(f"{t}{utemp}")
        if feels is not None:
            bits.append(f"feels like {feels}{utemp}")
        line1 = f"Weather in {place}: " + (", ".join(bits) if bits else "current conditions available.")
        line2_parts = []
        if wind is not None:
            line2_parts.append(f"wind {wind}{uwind}")
        if hum is not None:
            line2_parts.append(f"humidity {hum}%")
        if precip is not None:
            line2_parts.append(f"precip {precip}{uprec}")
        line2 = " • ".join(line2_parts)
        return line1 + (("\n" + line2) if line2 else "")

    def fmt_calendar_create(res: Dict[str, Any]) -> str:
        if res.get("ok") and res.get("event_id"):
            return f"Added it to your Calendar (event id: {res['event_id']})."
        return "I tried to add it to your Calendar, but it didn’t confirm creation."

    def fmt_hub_schedule(res: Dict[str, Any]) -> str:
        ev = (res.get("calendar_event") or {})
        suggested = res.get("suggested_time")
        msg = []
        if suggested:
            msg.append(f"Weather risk was higher than your limit, so I found a safer suggested time: {suggested}.")
        if ev.get("ok") and ev.get("event_id"):
            msg.append(f"Created the calendar event (event id: {ev['event_id']}).")
        elif ev:
            msg.append("Attempted to create the calendar event.")
        return "\n".join(msg) if msg else "Done."

    pick = last_ok or results[-1]
    tool = pick.get("tool", "")
    res = pick.get("result", {}) or {}

    if tool == "weather.current":
        return fmt_weather_current(res)
    if tool == "calendar.create_event":
        return fmt_calendar_create(res)
    if tool == "hub.schedule_drive_if_safe":
        return fmt_hub_schedule(res)

    return "Done. (Use --pretty to see full tool output.)"


def execute_action(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    # Weather
    if tool == "weather.open_weather_app":
        return weather.open_weather_app_impl()
    if tool == "weather.show_in_weather_app":
        return weather.show_in_weather_app_impl(args.get("place", ""))
    if tool == "weather.list_locations":
        return weather.list_locations_impl()
    if tool == "weather.add_location":
        return weather.add_location_impl(args.get("place", ""), bool(args.get("also_open_app", False)))
    if tool == "weather.remove_location":
        return weather.remove_location_impl(args.get("place", ""), bool(args.get("also_open_app", False)))
    if tool == "weather.set_home_location":
        return weather.set_home_location_impl(args.get("place", ""))
    if tool == "weather.set_units":
        return weather.set_units_impl(args.get("units", "C"))
    if tool == "weather.current":
        return weather.current_impl(args.get("place"))
    if tool == "weather.forecast_hourly":
        return weather.hourly_impl(args.get("place", ""), int(args.get("hours", 24)))
    if tool == "weather.forecast_daily":
        return weather.daily_impl(args.get("place", ""), int(args.get("days", 7)))
    if tool == "weather.risk":
        return weather.risk_impl(args.get("place", ""), args.get("iso_datetime", ""), args.get("activity", "driving"))
    if tool == "weather.best_time":
        return weather.best_time_impl(
            args.get("place", ""),
            args.get("activity", "driving"),
            args.get("start_dt", ""),
            args.get("end_dt", ""),
            int(args.get("step_minutes", 60)),
        )
    if tool == "weather.alerts":
        return weather.alerts_impl(
            args.get("place", ""),
            args.get("start_dt", ""),
            args.get("end_dt", ""),
            float(args.get("snow_threshold", 1.0)),
            float(args.get("rain_threshold", 5.0)),
            float(args.get("gust_threshold", 40.0)),
            float(args.get("visibility_threshold", 1000.0)),
        )

    # Calendar
    if tool == "calendar.open_calendar_app":
        return calendar.open_calendar_app_impl()
    if tool == "calendar.close_calendar_app":
        return calendar.close_calendar_app_impl()
    if tool == "calendar.list_calendars":
        return calendar.list_calendars_impl()
    if tool == "calendar.upcoming":
        return calendar.upcoming_impl(int(args.get("days", 7)), args.get("calendar_name"))
    if tool == "calendar.list_events":
        return calendar.list_events_impl(args.get("date_from", ""), args.get("date_to", ""), args.get("calendar_name"))
    if tool == "calendar.search_events":
        return calendar.search_events_impl(args.get("query", ""), args.get("date_from", ""), args.get("date_to", ""), args.get("calendar_name"))
    if tool == "calendar.create_event":
        return calendar.create_event_impl(
            args.get("title", ""),
            args.get("start", ""),
            args.get("end", ""),
            args.get("location"),
            args.get("notes"),
            args.get("calendar_name"),
        )
    if tool == "calendar.update_event":
        return calendar.update_event_impl(
            args.get("event_id", ""),
            title=args.get("title"),
            start=args.get("start"),
            end=args.get("end"),
            location=args.get("location"),
            notes=args.get("notes"),
        )
    if tool == "calendar.delete_event":
        return calendar.delete_event_impl(args.get("event_id", ""))
    if tool == "calendar.free_slots":
        return calendar.free_slots_impl(
            args.get("date_ymd", ""),
            int(args.get("duration_minutes", 30)),
            args.get("work_start", "09:00:00"),
            args.get("work_end", "17:00:00"),
        )

    # Hub
    if tool == "hub.schedule_drive_if_safe":
        return hub.schedule_drive_if_safe_impl(
            place=args.get("place", ""),
            start_dt=args.get("start_dt", ""),
            duration_minutes=int(args.get("duration_minutes", 45)),
            title=args.get("title", "Drive"),
            origin=args.get("origin"),
            destination=args.get("destination"),
            calendar_name=args.get("calendar_name"),
            activity=args.get("activity", "driving"),
            max_risk=args.get("max_risk", "low"),
            fallback_window_minutes=int(args.get("fallback_window_minutes", 240)),
        )
    if tool == "hub.reschedule_event_if_weather_bad":
        return hub.reschedule_event_if_weather_bad_impl(
            event_id=args.get("event_id", ""),
            place=args.get("place", ""),
            start_dt=args.get("start_dt", ""),
            end_dt=args.get("end_dt", ""),
            activity=args.get("activity", "driving"),
            max_risk=args.get("max_risk", "low"),
            window_end_dt=args.get("window_end_dt"),
        )

    return {"ok": False, "error": f"Unknown tool: {tool}", "args": args}


def main():
    import sys
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args()
    
    if not args.query:
        print("Usage: python chat_cli.py '<query>' [--dry_run] [--pretty] [--human]")
        return
    
    output = {"input": args.query}
    plan_result = plan(args.query)
    output["plan"] = plan_result
    
    if args.dry_run:
        print(json.dumps(output, indent=2 if args.pretty else None))
        return
    
    # Execute actions
    results = []
    for action in plan_result.get("actions", []):
        tool = action["tool"]
        args_dict = action.get("args", {})
        result = execute_action(tool, args_dict)
        results.append({"tool": tool, "args": args_dict, "result": result})
    
    output["results"] = results

    # --- auto-delete (existing) ---
    # Check if user asked to delete and we found events
    user_text_lower = args.query.lower()
    if any(word in user_text_lower for word in ["delete", "remove"]):
        for r in results:
            # Handle both search_events and list_events
            if r["tool"] in ["calendar.search_events", "calendar.list_events"] and r["result"].get("ok"):
                events = r["result"].get("events", [])
                for evt in events:
                    # Auto-delete found events
                    delete_result = execute_action("calendar.delete_event", {"event_id": evt["event_id"]})
                    results.append({"tool": "calendar.delete_event", "args": {"event_id": evt["event_id"]}, "result": delete_result})
    
    # --- end auto-delete ---

    # Auto-update/reschedule when user asks to update/reschedule and a search/list returned events
    user_text_lower = args.query.lower()
    if any(w in user_text_lower for w in ["update", "reschedule", "move", "change"]):
        for r in results:
            if r["tool"] in ["calendar.search_events", "calendar.list_events"] and r["result"].get("ok"):
                events = r["result"].get("events", [])
                if not events:
                    continue
                evt = events[0]  # update first matched
                # parse explicit date in user text (YYYY-MM-DD) or use event's date
                import re
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', user_text_lower)
                ev_date = None
                if date_match:
                    ev_date = date_match.group(1)
                else:
                    dm = re.search(r'(\w+),\s+(\w+)\s+(\d{1,2}),\s+(\d{4})', evt.get("start",""))
                    if dm:
                        month = dm.group(2); day = int(dm.group(3)); year = dm.group(4)
                        # reuse _month_to_num helper
                        ev_date = f"{year}-{_month_to_num(month)}-{day:02d}"
                # parse explicit time range like "3pm-4pm" or "3pm to 4pm"
                range_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', user_text_lower)
                single_match = re.search(r'at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', user_text_lower)
                update_args = {"event_id": evt["event_id"]}
                if range_match and ev_date:
                    sh = int(range_match.group(1)); sm = int(range_match.group(2) or 0); sap = range_match.group(3)
                    eh = int(range_match.group(4)); em = int(range_match.group(5) or 0); eap = range_match.group(6) or sap
                    sh, sm = _to_24h(sh, sm, sap)
                    eh, em = _to_24h(eh, em, eap)
                    update_args["start"] = f"{ev_date} {sh:02d}:{sm:02d}:00"
                    update_args["end"] = f"{ev_date} {eh:02d}:{em:02d}:00"
                elif single_match and ev_date:
                    h = int(single_match.group(1)); m = int(single_match.group(2) or 0); ap = single_match.group(3)
                    h, m = _to_24h(h, m, ap)
                    # preserve original duration
                    import re as _re
                    orig_start_m = _re.search(r'at\s+(\d{1,2}):(\d{2}):(\d{2})\s+([AP]M)', evt.get("start","").upper())
                    orig_end_m = _re.search(r'at\s+(\d{1,2}):(\d{2}):(\d{2})\s+([AP]M)', evt.get("end","").upper())
                    if orig_start_m and orig_end_m:
                        os_h = int(orig_start_m.group(1)); os_m = int(orig_start_m.group(2)); osa = orig_start_m.group(4)
                        oe_h = int(orig_end_m.group(1)); oe_m = int(orig_end_m.group(2)); oea = orig_end_m.group(4)
                        os_h, os_m = _to_24h(os_h, os_m, osa)
                        oe_h, oe_m = _to_24h(oe_h, oe_m, oea)
                        dur = (oe_h*60+oe_m) - (os_h*60+os_m)
                    else:
                        dur = 60
                    end_total = h*60 + m + dur
                    eh = end_total // 60; em = end_total % 60
                    update_args["start"] = f"{ev_date} {h:02d}:{m:02d}:00"
                    update_args["end"] = f"{ev_date} {eh:02d}:{em:02d}:00"
                # perform update if we have start/end
                if "start" in update_args or "end" in update_args:
                    upd_res = execute_action("calendar.update_event", update_args)
                    results.append({"tool": "calendar.update_event", "args": update_args, "result": upd_res})

    if args.human:
        print(render_human(output))
    else:
        print(json.dumps(output, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
