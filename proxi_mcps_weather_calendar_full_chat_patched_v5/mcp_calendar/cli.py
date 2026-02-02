
from __future__ import annotations
import argparse, json
from ...proxi.mcp.calendar import impl

def main():
    p = argparse.ArgumentParser(description="Calendar MCP local test harness (calls impl directly)")
    p.add_argument("action", help="open_calendar_app | list_calendars | list_events | upcoming | search | create | update | delete | free_slots")
    p.add_argument("args", nargs="*")
    p.add_argument("--location", default=None)
    p.add_argument("--notes", default=None)
    p.add_argument("--calendar", default=None)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--duration", type=int, default=30)
    a = p.parse_args()

    def out(x): print(json.dumps(x, indent=2))

    if a.action == "open_calendar_app":
        out(impl.open_calendar_app_impl())
    elif a.action == "list_calendars":
        out(impl.list_calendars_impl())
    elif a.action == "list_events":
        if len(a.args) < 2:
            out({"ok": False, "error": "Usage: list_events <from> <to>"})
        else:
            out(impl.list_events_impl(a.args[0], a.args[1], a.calendar))
    elif a.action == "upcoming":
        out(impl.upcoming_impl(a.days, a.calendar))
    elif a.action == "search":
        if len(a.args) < 3:
            out({"ok": False, "error": "Usage: search <query> <from> <to>"})
        else:
            out(impl.search_events_impl(a.args[0], a.args[1], a.args[2], a.calendar))
    elif a.action == "create":
        if len(a.args) < 3:
            out({"ok": False, "error": "Usage: create <title> <start> <end>"})
        else:
            out(impl.create_event_impl(a.args[0], a.args[1], a.args[2], a.location, a.notes, a.calendar))
    elif a.action == "update":
        if len(a.args) < 1:
            out({"ok": False, "error": "Usage: update <event_id> [--notes ...] etc"})
        else:
            out(impl.update_event_impl(a.args[0], notes=a.notes, location=a.location))
    elif a.action == "delete":
        if len(a.args) < 1:
            out({"ok": False, "error": "Usage: delete <event_id>"})
        else:
            out(impl.delete_event_impl(a.args[0]))
    elif a.action == "free_slots":
        if len(a.args) < 1:
            out({"ok": False, "error": "Usage: free_slots <YYYY-MM-DD> --duration 45"})
        else:
            out(impl.free_slots_impl(a.args[0], duration_minutes=a.duration))
    else:
        out({"ok": False, "error": f"Unknown action: {a.action}"})

if __name__ == "__main__":
    main()
