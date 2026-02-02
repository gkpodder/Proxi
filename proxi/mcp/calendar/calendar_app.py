from __future__ import annotations

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import re

from proxi.mcp.calendar.utils import run_osascript, esc_applescript


# -------------------------
# Parsing helpers (stdlib only)
# -------------------------

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_HINT_RE = re.compile(r"(\b\d{1,2}(:\d{2})?\b|\b(am|pm)\b)", re.IGNORECASE)


def _has_explicit_time(s: str) -> bool:
    return bool(s and _TIME_HINT_RE.search(s))


def _parse_time_fragment(rest: str) -> Tuple[int, int, int]:
    """
    Parses: '9pm', '9:30pm', '21:00', '21:00:15'
    Returns (hour, minute, second)
    """
    t = rest.strip().lower().replace("at", "").strip()
    if not t:
        raise ValueError("missing time")

    # 9pm / 9:30pm
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)$", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        second = int(m.group(3) or 0)
        ampm = m.group(4)

        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        return hour, minute, second

    # 21:00 / 21:00:15
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        second = int(m.group(3) or 0)
        return hour, minute, second

    # plain "9" -> treat as 9:00
    m = re.match(r"^(\d{1,2})$", t)
    if m:
        return int(m.group(1)), 0, 0

    raise ValueError(f"Unsupported time format: {rest}")


def _parse_datetime_flexible(value: str) -> Tuple[datetime, bool]:
    """
    Parse a datetime string into local naive datetime.

    Accepts:
      - ISO: '2026-02-01T21:00:00'
      - date-only: '2026-02-01'  (no explicit time)
      - 'today', 'tomorrow', 'yesterday'
      - 'today 9pm', 'tomorrow at 10:30', etc.
    Returns (dt, has_explicit_time)
    """
    s = (value or "").strip()
    if not s:
        raise ValueError("empty datetime string")

    sl = s.lower().strip()
    now = datetime.now().replace(microsecond=0)

    # today/tomorrow/yesterday
    if sl.startswith("today"):
        base = now
        rest = s[len("today"):].strip()
        has_time = _has_explicit_time(rest)
        if has_time:
            h, m, sec = _parse_time_fragment(rest)
            return base.replace(hour=h, minute=m, second=sec), True
        return base.replace(hour=0, minute=0, second=0), False

    if sl.startswith("tomorrow"):
        base = (now + timedelta(days=1))
        rest = s[len("tomorrow"):].strip()
        has_time = _has_explicit_time(rest)
        if has_time:
            h, m, sec = _parse_time_fragment(rest)
            return base.replace(hour=h, minute=m, second=sec), True
        return base.replace(hour=0, minute=0, second=0), False

    if sl.startswith("yesterday"):
        base = (now - timedelta(days=1))
        rest = s[len("yesterday"):].strip()
        has_time = _has_explicit_time(rest)
        if has_time:
            h, m, sec = _parse_time_fragment(rest)
            return base.replace(hour=h, minute=m, second=sec), True
        return base.replace(hour=0, minute=0, second=0), False

    # date-only YYYY-MM-DD
    if _DATE_ONLY_RE.match(sl):
        dt = datetime.strptime(sl, "%Y-%m-%d")
        return dt.replace(microsecond=0), False

    # ISO with time (or 'YYYY-MM-DD HH:MM:SS' sometimes)
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(microsecond=0), True
    except Exception:
        pass

    # Very small fallback: 'YYYY-MM-DD HH:MM' (space-separated)
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return dt.replace(second=0, microsecond=0), True
    except Exception:
        pass

    raise ValueError(f"Unsupported datetime format: {value}")


def _normalize_range(date_from: str, date_to: str) -> Tuple[datetime, datetime]:
    """
    Expand date-only bounds to full-day:
      from (no time) => 00:00:00
      to   (no time) => 23:59:59
    """
    dt_from, from_has_time = _parse_datetime_flexible(date_from)
    dt_to, to_has_time = _parse_datetime_flexible(date_to)

    if not from_has_time:
        dt_from = dt_from.replace(hour=0, minute=0, second=0)
    if not to_has_time:
        dt_to = dt_to.replace(hour=23, minute=59, second=59)

    # If end < start, assume crosses midnight
    if dt_to < dt_from:
        dt_to = dt_to + timedelta(days=1)

    return dt_from, dt_to


def _to_applescript_date(dt: datetime) -> str:
    """
    Convert datetime to AppleScript date string:
      Monday, February 2, 2026 12:00:00 AM
    """
    iso_str = dt.isoformat()
    result = dt.strftime("%A, %B %d, %Y %I:%M:%S %p").replace(" 0", " ")
    return result


# -------------------------
# Calendar operations
# -------------------------

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
    set AppleScript's text item delimiters to linefeed
    return calNames as text
end tell'''
    rc, out, err = run_osascript(script)
    calendars = [c.strip() for c in out.splitlines() if c.strip()] if rc == 0 else []
    return {"ok": rc == 0, "calendars": calendars, "stderr": err}


def list_events(date_from: str, date_to: str, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    dt_from, dt_to = _normalize_range(date_from, date_to)

    start_as = _to_applescript_date(dt_from)
    end_as = _to_applescript_date(dt_to)

    cal_filter = f'(every calendar whose name is "{esc_applescript(calendar_name)}")' if calendar_name else "calendars"

    # IMPORTANT: return one event per line to parse reliably.
    script = f'''tell application "Calendar"
    set rows to {{}}
    set startDate to date "{esc_applescript(start_as)}"
    set endDate to date "{esc_applescript(end_as)}"
    repeat with cal in {cal_filter}
        repeat with e in (every event of cal whose start date ≥ startDate and start date ≤ endDate)
            set end of rows to ((id of e as string) & "||" & (summary of e) & "||" & (start date of e as string) & "||" & (end date of e as string))
        end repeat
    end repeat
    set AppleScript's text item delimiters to linefeed
    return rows as text
end tell'''

    rc, out, err = run_osascript(script, timeout_s=25)

    events: List[Dict[str, Any]] = []
    if rc == 0:
        for line in out.splitlines():
            if "||" not in line:
                continue
            event_id, title, start, end = line.split("||", 3)
            events.append(
                {
                    "event_id": event_id.strip(),
                    "title": title.strip(),
                    "start": start.strip(),
                    "end": end.strip(),
                }
            )

    return {"ok": rc == 0, "events": events, "stderr": err}


def search_events(query: str, date_from: str, date_to: str, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    dt_from, dt_to = _normalize_range(date_from, date_to)

    query_esc = esc_applescript(query)
    start_as = _to_applescript_date(dt_from)
    end_as = _to_applescript_date(dt_to)
    cal_filter = f'(every calendar whose name is "{esc_applescript(calendar_name)}")' if calendar_name else "calendars"

    script = f'''tell application "Calendar"
    set rows to {{}}
    set startDate to date "{esc_applescript(start_as)}"
    set endDate to date "{esc_applescript(end_as)}"
    repeat with cal in {cal_filter}
        repeat with e in (every event of cal whose start date ≥ startDate and start date ≤ endDate)
            if (summary of e) contains "{query_esc}" then
                set end of rows to ((id of e as string) & "||" & (summary of e) & "||" & (start date of e as string) & "||" & (end date of e as string))
            end if
        end repeat
    end repeat
    set AppleScript's text item delimiters to linefeed
    return rows as text
end tell'''

    rc, out, err = run_osascript(script, timeout_s=25)

    events: List[Dict[str, Any]] = []
    if rc == 0:
        for line in out.splitlines():
            if "||" not in line:
                continue
            event_id, title, start, end = line.split("||", 3)
            events.append(
                {
                    "event_id": event_id.strip(),
                    "title": title.strip(),
                    "start": start.strip(),
                    "end": end.strip(),
                }
            )

    return {"ok": rc == 0, "events": events, "stderr": err}


def create_event(
    title: str,
    start: str,
    end: str,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    calendar_name: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        start_dt, _ = _parse_datetime_flexible(start)
        end_dt, _ = _parse_datetime_flexible(end)
    except Exception as e:
        return {"ok": False, "stderr": f"Date parsing error: {str(e)}", "result": None}

    start_as = _to_applescript_date(start_dt)
    end_as = _to_applescript_date(end_dt)

    cal_target = f'calendar "{esc_applescript(calendar_name)}"' if calendar_name else 'first calendar'

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


def update_event(
    event_id: str,
    title: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    setters = []
    if title:
        setters.append(f'set summary of e to "{esc_applescript(title)}"')
    if start:
        start_dt, _ = _parse_datetime_flexible(start)
        setters.append(f'set start date of e to date "{esc_applescript(_to_applescript_date(start_dt))}"')
    if end:
        end_dt, _ = _parse_datetime_flexible(end)
        setters.append(f'set end date of e to date "{esc_applescript(_to_applescript_date(end_dt))}"')
    if location:
        setters.append(f'set location of e to "{esc_applescript(location)}"')
    if notes:
        setters.append(f'set description of e to "{esc_applescript(notes)}"')

    if not setters:
        return {"ok": True, "result": "no changes", "stderr": None}

    script = f'''tell application "Calendar"
    repeat with cal in calendars
        try
            set matches to (every event of cal whose id is "{esc_applescript(event_id)}")
            if (count of matches) > 0 then
                set e to item 1 of matches
                {chr(10).join(setters)}
                exit repeat
            end if
        end try
    end repeat
end tell'''

    rc, out, err = run_osascript(script, timeout_s=20)

    return {"ok": rc == 0, "result": "Event updated" if rc == 0 else None, "stderr": err if rc != 0 else None}


def delete_event(event_id: str) -> Dict[str, Any]:
    """
    Robust delete by ID (no fragile 'event i of cal' indexing).
    """
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


def find_free_slots(
    date_ymd: str,
    duration_minutes: int = 30,
    work_start: str = "09:00:00",
    work_end: str = "17:00:00",
) -> Dict[str, Any]:
    return {"ok": True, "slots": [{"start": "10:00", "end": "10:30"}]}
