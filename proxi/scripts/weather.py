"""CLI wrapper for Open-Meteo weather queries.

Exit code contract:
  0 — Script ran to completion. stdout is a JSON object.
      The JSON may contain an "error" key if the API reported a problem
      (e.g. location not found). The agent reads the JSON and decides whether
      to retry or ask the user — it does not treat exit 0 as "all good".
  1 — Unrecoverable script failure (network totally down, bad arguments,
      unexpected exception). stdout is a JSON object with "error" and "hint"
      keys so the agent gets a structured, actionable message rather than a
      raw Python traceback.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query Open-Meteo weather API",
        # Disable abbreviation matching to prevent partial-flag confusion.
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    cur = sub.add_parser("current", help="Get current weather", allow_abbrev=False)
    cur.add_argument("--location", required=True, help="City or place name")
    cur.add_argument(
        "--unit",
        choices=["celsius", "fahrenheit"],
        default="celsius",
        help="Temperature unit",
    )

    fct = sub.add_parser(
        "forecast", help="Get multi-day weather forecast", allow_abbrev=False
    )
    fct.add_argument("--location", required=True, help="City or place name")
    fct.add_argument("--days", type=int, default=3, help="Forecast days (1-7)")
    fct.add_argument(
        "--unit",
        choices=["celsius", "fahrenheit"],
        default="celsius",
        help="Temperature unit",
    )

    args = parser.parse_args()

    try:
        from proxi.mcp.servers.weather_tools import WeatherTools

        wt = WeatherTools()

        if args.cmd == "current":
            result = asyncio.run(wt.get_current_weather(args.location, args.unit))
        else:
            result = asyncio.run(wt.get_forecast(args.location, args.days, args.unit))

        # Always exit 0 when we got a response from the API — even if it contains
        # an "error" key. The agent reads the JSON and handles the error itself
        # (e.g. by retrying with a more explicit location string).
        print(json.dumps(result))
        sys.exit(0)

    except (urllib.error.URLError, TimeoutError) as e:
        # Transient network failure — the agent should retry.
        print(json.dumps({
            "error": str(e),
            "hint": "Transient network error. Retrying may succeed.",
        }))
        sys.exit(3)
    except Exception as e:
        # Unrecoverable failure: import error, bad args, logic error, etc.
        # Emit structured JSON so the agent gets an actionable message
        # rather than a raw Python traceback.
        print(json.dumps({
            "error": str(e),
            "hint": (
                "This is a script-level failure, not an API error. "
                "Check network connectivity or try again."
            ),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
