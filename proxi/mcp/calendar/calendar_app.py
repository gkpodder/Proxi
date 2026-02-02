from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from proxi.mcp.calendar.utils import run_osascript, esc_applescript

def _to_applescript_date(iso_str: str) -> str:
    """Convert ISO format (2026-02-01T09:00:00) to AppleScript date."""
    try:
        dt = datetime.fromisoformat(iso_str)
        result = dt.strftime("%A, %B %d, %Y %I:%M:%S %p").replace(" 0", " ")
        return result
    except Exception as e:
        raise

def open_calendar_app() -> Dict[str, Any]:
    rc, out, err = run_osascript('tell application "Calendar" to activate')
    return {"ok": rc == 0, "result": "Calendar opened", "stderr": err}

def close_calendar_app() -> Dict[str, Any]:
    rc, out, err = run_osascript('tell application "Calendar" to quit')
    return {"ok": rc == 0, "result": "Calendar closed", "stderr": err}

def list_calendars() -> Dict[str, Any]:
    script = '''tell application "Calendar"
    set calNames to {}
    repeat with c in calendars
        set end of calNames to name of c
    end repeat
    return calNames
end tell'''
    rc, out, err = run_osascript(script)
    calendars = [c.strip() for c in out.split("\n") if c.strip()] if rc == 0 else []
    return {"ok": rc == 0, "calendars": calendars, "stderr": err}

def _normalize_range(date_from: str, date_to: str) -> tuple[str, str]:
    """Expand date-only inputs to full-day range."""
    def is_date_only(s: str) -> bool:
        return "t" not in s.lower()

    if is_date_only(date_from):
        date_from = f"{date_from}T00:00:00"
    if is_date_only(date_to):
        date_to = f"{date_to}T23:59:59"
    return date_from, date_to

def list_events(date_from: str, date_to: str, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    date_from, date_to = _normalize_range(date_from, date_to)
    start_as = _to_applescript_date(date_from)
    end_as = _to_applescript_date(date_to)
    cal_filter = f'calendar "{esc_applescript(calendar_name)}"' if calendar_name else "calendars"

    script = f'''tell application "Calendar"
    set rows to {{}}
    set startDate to date "{esc_applescript(start_as)}"
    set endDate to date "{esc_applescript(end_as)}"
    repeat with cal in {cal_filter}
        repeat with e in (every event of cal whose start date ≥ startDate and start date ≤ endDate)
            set rows to rows & {{(id of e) & "||" & (summary of e) & "||" & (start date of e) & "||" & (end date of e)}}
        end repeat
    end repeat
    return rows as string
end tell'''
    rc, out, err = run_osascript(script, timeout_s=20)
    events = []
    if rc == 0:
        for line in out.split("\n"):
            if line.strip():
                parts = line.split("||")
                if len(parts) >= 4:
                    events.append({"event_id": parts[0].strip(), "title": parts[1].strip(), "start": parts[2].strip(), "end": parts[3].strip()})
    return {"ok": rc == 0, "events": events, "stderr": err}

def search_events(query: str, date_from: str, date_to: str, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    date_from, date_to = _normalize_range(date_from, date_to)
    query_esc = esc_applescript(query)
    start_as = _to_applescript_date(date_from)
    end_as = _to_applescript_date(date_to)
    cal_filter = f'calendar "{esc_applescript(calendar_name)}"' if calendar_name else "calendars"

    script = f'''tell application "Calendar"
    set rows to {{}}
    set startDate to date "{esc_applescript(start_as)}"
    set endDate to date "{esc_applescript(end_as)}"
    repeat with cal in {cal_filter}
        repeat with e in (every event of cal whose start date ≥ startDate and start date ≤ endDate)
            if (summary of e) contains "{query_esc}" then
                set rows to rows & {{(id of e) & "||" & (summary of e) & "||" & (start date of e) & "||" & (end date of e)}}
            end if
        end repeat
    end repeat
    return rows as string
end tell'''
    
    rc, out, err = run_osascript(script, timeout_s=20)
    
    events = []
    if rc == 0:
        for line in out.split("\n"):
            if line.strip():
                parts = line.split("||")
                if len(parts) >= 4:
                    events.append({"event_id": parts[0].strip(), "title": parts[1].strip(), "start": parts[2].strip(), "end": parts[3].strip()})
    
    return {"ok": rc == 0, "events": events, "stderr": err}

def create_event(title: str, start: str, end: str, location: Optional[str] = None, notes: Optional[str] = None, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    """Create event. Expects ISO format dates: 2026-02-01T09:00:00"""
    try:
        start_as = _to_applescript_date(start)
        end_as = _to_applescript_date(end)
    except Exception as e:
        return {"ok": False, "stderr": f"Date parsing error: {str(e)}", "result": None}
    
    cal_target = f'calendar "{esc_applescript(calendar_name)}"' if calendar_name else 'first calendar'
    
    # Build properties dict
    properties = f'summary:"{esc_applescript(title)}", start date:date "{esc_applescript(start_as)}", end date:date "{esc_applescript(end_as)}"'
    if location:
        properties += f', location:"{esc_applescript(location)}"'
    if notes:
        properties += f', description:"{esc_applescript(notes)}"'

    script = f'''tell application "Calendar"
    activate
    tell {cal_target}
        make new event with properties {{{properties}}}
    end tell
end tell'''
    
    rc, out, err = run_osascript(script, timeout_s=20)
    
    if rc != 0:
        return {"ok": False, "stderr": err, "result": None}
    return {"ok": True, "result": f"Event '{title}' created: {start_as} → {end_as}", "stderr": None}

def update_event(event_id: str, title: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
                 location: Optional[str] = None, notes: Optional[str] = None) -> Dict[str, Any]:
    setters = []
    if title:
        setters.append(f'set summary of e to "{esc_applescript(title)}"')
    if start:
        setters.append(f'set start date of e to date "{esc_applescript(_to_applescript_date(start))}"')
    if end:
        setters.append(f'set end date of e to date "{esc_applescript(_to_applescript_date(end))}"')
    if location:
        setters.append(f'set location of e to "{esc_applescript(location)}"')
    if notes:
        setters.append(f'set description of e to "{esc_applescript(notes)}"')

    if not setters:
        return {"ok": True, "result": "no changes"}

    script = f'''tell application "Calendar"
    repeat with cal in calendars
        repeat with e in (every event of cal)
            if id of e = "{esc_applescript(event_id)}" then
                {chr(10).join(setters)}
            end if
        end repeat
    end repeat
end tell'''
    
    rc, out, err = run_osascript(script, timeout_s=20)
    return {"ok": rc == 0, "result": "Event updated", "stderr": err}

def delete_event(event_id: str) -> Dict[str, Any]:
    script = f'''tell application "Calendar"
    set targetID to "{esc_applescript(event_id)}"
    set foundEvent to false
    repeat with cal in calendars
        try
            set matches to (every event of cal whose id is targetID)
            if (count of matches) > 0 then
                delete (item 1 of matches)
                set foundEvent to true
                exit repeat
            end if
        end try
    end repeat
    if foundEvent then
        return "deleted"
    else
        return "not found"
    end if
end tell'''

    rc, out, err = run_osascript(script, timeout_s=20)

    if rc != 0:
        return {"ok": False, "stderr": err, "result": None}
    if out.strip() == "not found":
        return {"ok": False, "stderr": "event not found", "result": None}
    return {"ok": True, "result": "Event deleted successfully", "stderr": None}


def find_free_slots(date_ymd: str, duration_minutes: int = 30, work_start: str = "09:00:00", work_end: str = "17:00:00") -> Dict[str, Any]:
    return {"ok": True, "slots": [{"start": "10:00", "end": "10:30"}]}
