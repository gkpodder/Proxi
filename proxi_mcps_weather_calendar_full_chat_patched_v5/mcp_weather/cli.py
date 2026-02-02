
from __future__ import annotations
import argparse, json
from . import impl

def main():
    p = argparse.ArgumentParser(description="Weather MCP local test harness (calls impl directly)")
    p.add_argument("action", help="open_weather_app | show_in_weather_app | list_locations | add_location | remove_location | set_home | set_units | current | daily | hourly | risk | best_time | alerts")
    p.add_argument("args", nargs="*")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--also_open_app", action="store_true")
    p.add_argument("--step_minutes", type=int, default=60)
    p.add_argument("--snow_threshold", type=float, default=1.0)
    p.add_argument("--rain_threshold", type=float, default=5.0)
    p.add_argument("--gust_threshold", type=float, default=40.0)
    p.add_argument("--visibility_threshold", type=float, default=1000.0)
    a = p.parse_args()

    def out(x): print(json.dumps(x, indent=2))

    if a.action == "open_weather_app":
        out(impl.open_weather_app_impl())
    elif a.action == "show_in_weather_app":
        out(impl.show_in_weather_app_impl(" ".join(a.args)))
    elif a.action == "list_locations":
        out(impl.list_locations_impl())
    elif a.action == "add_location":
        out(impl.add_location_impl(" ".join(a.args), also_open_app=a.also_open_app))
    elif a.action == "remove_location":
        out(impl.remove_location_impl(" ".join(a.args), also_open_app=a.also_open_app))
    elif a.action == "set_home":
        out(impl.set_home_location_impl(" ".join(a.args)))
    elif a.action == "set_units":
        out(impl.set_units_impl(" ".join(a.args)))
    elif a.action == "current":
        place = " ".join(a.args) if a.args else None
        out(impl.current_impl(place))
    elif a.action == "daily":
        out(impl.daily_impl(" ".join(a.args), days=a.days))
    elif a.action == "hourly":
        out(impl.hourly_impl(" ".join(a.args), hours=a.hours))
    elif a.action == "risk":
        if len(a.args) < 2:
            out({"ok": False, "error": "Usage: risk <place> <datetime> [activity]"})
        else:
            place, dt = a.args[0], a.args[1]
            act = a.args[2] if len(a.args) >= 3 else "driving"
            out(impl.risk_impl(place, dt, act))
    elif a.action == "best_time":
        if len(a.args) < 4:
            out({"ok": False, "error": "Usage: best_time <place> <activity> <start_dt> <end_dt>"})
        else:
            out(impl.best_time_impl(a.args[0], a.args[1], a.args[2], a.args[3], step_minutes=a.step_minutes))
    elif a.action == "alerts":
        if len(a.args) < 3:
            out({"ok": False, "error": "Usage: alerts <place> <start_dt> <end_dt>"})
        else:
            out(impl.alerts_impl(a.args[0], a.args[1], a.args[2], a.snow_threshold, a.rain_threshold, a.gust_threshold, a.visibility_threshold))
    else:
        out({"ok": False, "error": f"Unknown action: {a.action}"})

if __name__ == "__main__":
    main()
