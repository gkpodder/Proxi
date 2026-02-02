
from __future__ import annotations
import argparse, json
from . import impl

def main():
    p = argparse.ArgumentParser(description="Hub MCP local test harness (calls impl directly)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("schedule_drive_if_safe")
    s1.add_argument("place")
    s1.add_argument("start_dt")
    s1.add_argument("duration_minutes", type=int)
    s1.add_argument("--title", default="Drive")
    s1.add_argument("--origin", default=None)
    s1.add_argument("--destination", default=None)
    s1.add_argument("--calendar", default=None)
    s1.add_argument("--max_risk", default="low")

    s2 = sub.add_parser("reschedule_event_if_weather_bad")
    s2.add_argument("event_id")
    s2.add_argument("place")
    s2.add_argument("start_dt")
    s2.add_argument("end_dt")
    s2.add_argument("--max_risk", default="low")

    a = p.parse_args()
    if a.cmd == "schedule_drive_if_safe":
        res = impl.schedule_drive_if_safe_impl(
            place=a.place, start_dt=a.start_dt, duration_minutes=a.duration_minutes,
            title=a.title, origin=a.origin, destination=a.destination, calendar_name=a.calendar, max_risk=a.max_risk
        )
    else:
        res = impl.reschedule_event_if_weather_bad_impl(
            event_id=a.event_id, place=a.place, start_dt=a.start_dt, end_dt=a.end_dt, max_risk=a.max_risk
        )
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
