"""CLI wrapper for Calendar MCP tool operations.

Exit code contract:
  0 - Script ran to completion. stdout is a JSON object.
      The JSON may contain an "error" key if the API reported a problem.
  1 - Unrecoverable script failure (bad args, import error, unexpected exception).
      stdout is a JSON object with "error" and "hint".
  3 - Transient network failure. stdout is a JSON object with "error" and "hint".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import urllib.error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Calendar operations via CLI",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_cmd = sub.add_parser("list-events", help="List events", allow_abbrev=False)
    list_cmd.add_argument("--max-results", type=int, default=10, help="Max events")
    list_cmd.add_argument("--calendar-id", default="primary", help="Calendar ID")
    list_cmd.add_argument("--time-min", default=None, help="RFC3339 lower bound")
    list_cmd.add_argument("--time-max", default=None, help="RFC3339 upper bound")
    list_cmd.add_argument("--query", default="", help="Search text")

    create = sub.add_parser("create-event", help="Create event", allow_abbrev=False)
    create.add_argument("--summary", required=True, help="Event title")
    create.add_argument("--start-time", required=True, help="Start datetime/time text")
    create.add_argument("--end-time", required=True, help="End datetime/time text")
    create.add_argument("--timezone", required=True, help="IANA timezone")
    create.add_argument("--calendar-id", default="primary", help="Calendar ID")
    create.add_argument("--attendees", action="append", help="Attendee email", default=None)
    create.add_argument("--description", default=None, help="Description")
    create.add_argument("--location", default=None, help="Location")

    get = sub.add_parser("get-event", help="Get event", allow_abbrev=False)
    get.add_argument("--event-id", required=True, help="Event ID")
    get.add_argument("--calendar-id", default="primary", help="Calendar ID")

    update = sub.add_parser("update-event", help="Update event", allow_abbrev=False)
    update.add_argument("--event-id", required=True, help="Event ID")
    update.add_argument("--calendar-id", default="primary", help="Calendar ID")
    update.add_argument("--summary", default=None, help="Updated title")
    update.add_argument("--start-time", default=None, help="Updated start datetime")
    update.add_argument("--end-time", default=None, help="Updated end datetime")
    update.add_argument("--timezone", default=None, help="Updated timezone")
    update.add_argument("--attendees", action="append", help="Updated attendee email", default=None)
    update.add_argument("--description", default=None, help="Updated description")
    update.add_argument("--location", default=None, help="Updated location")

    delete = sub.add_parser("delete-event", help="Delete event", allow_abbrev=False)
    delete.add_argument("--event-id", required=True, help="Event ID")
    delete.add_argument("--calendar-id", default="primary", help="Calendar ID")

    args = parser.parse_args()

    try:
        from proxi.mcp.servers.calendar_tools import CalendarTools

        tools = CalendarTools()

        if args.cmd == "list-events":
            result = asyncio.run(
                tools.list_events(
                    max_results=args.max_results,
                    calendar_id=args.calendar_id,
                    time_min=args.time_min,
                    time_max=args.time_max,
                    query=args.query,
                )
            )
        elif args.cmd == "create-event":
            result = asyncio.run(
                tools.create_event(
                    summary=args.summary,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    timezone_name=args.timezone,
                    calendar_id=args.calendar_id,
                    attendees=args.attendees,
                    description=args.description,
                    location=args.location,
                )
            )
        elif args.cmd == "get-event":
            result = asyncio.run(tools.get_event(args.event_id, args.calendar_id))
        elif args.cmd == "update-event":
            result = asyncio.run(
                tools.update_event(
                    event_id=args.event_id,
                    calendar_id=args.calendar_id,
                    summary=args.summary,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    timezone_name=args.timezone,
                    attendees=args.attendees,
                    description=args.description,
                    location=args.location,
                )
            )
        else:
            result = asyncio.run(tools.delete_event(args.event_id, args.calendar_id))

        print(json.dumps(result))
        sys.exit(0)

    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        print(
            json.dumps(
                {
                    "error": str(e),
                    "hint": "Transient network error. Retrying may succeed.",
                }
            )
        )
        sys.exit(3)
    except Exception as e:
        print(
            json.dumps(
                {
                    "error": str(e),
                    "hint": (
                        "This is a script-level failure, not an API error. "
                        "Check Calendar credentials/config or try again."
                    ),
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
