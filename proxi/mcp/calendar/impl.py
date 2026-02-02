from __future__ import annotations
from typing import Dict, Any, Optional
from .calendar_app import (
    open_calendar_app,
    close_calendar_app,
    list_calendars,
    list_events,
    search_events,
    create_event,
    update_event,
    delete_event,
    find_free_slots,
)

__all__ = [
    "open_calendar_app",
    "close_calendar_app",
    "list_calendars",
    "list_events",
    "search_events",
    "create_event",
    "update_event",
    "delete_event",
    "find_free_slots",
]

def open_calendar_app_impl() -> Dict[str, Any]:
    return open_calendar_app()

def close_calendar_app_impl() -> Dict[str, Any]:
    return close_calendar_app()

def list_calendars_impl() -> Dict[str, Any]:
    return list_calendars()

def list_events_impl(date_from: str, date_to: str, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    return list_events(date_from, date_to, calendar_name)

def upcoming_impl(days: int = 7, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now().replace(microsecond=0)
    end = now + timedelta(days=max(1,int(days)))
    return list_events(now.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), calendar_name)

def search_events_impl(query: str, date_from: str, date_to: str, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    return search_events(query, date_from, date_to, calendar_name)

def create_event_impl(title: str, start: str, end: str, location: Optional[str] = None, notes: Optional[str] = None, calendar_name: Optional[str] = None) -> Dict[str, Any]:
    return create_event(title, start, end, location, notes, calendar_name)

def update_event_impl(event_id: str, title: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
                      location: Optional[str] = None, notes: Optional[str] = None) -> Dict[str, Any]:
    return update_event(event_id, title, start, end, location, notes)

def delete_event_impl(event_id: str) -> Dict[str, Any]:
    return delete_event(event_id)

def free_slots_impl(date_ymd: str, duration_minutes: int = 30, work_start: str = "09:00:00", work_end: str = "17:00:00") -> Dict[str, Any]:
    return find_free_slots(date_ymd, duration_minutes, work_start, work_end)
