"""CLI wrapper for Open-Meteo weather queries."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Open-Meteo weather API")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cur = sub.add_parser("current", help="Get current weather")
    cur.add_argument("--location", required=True, help="City or place name")
    cur.add_argument(
        "--unit",
        choices=["celsius", "fahrenheit"],
        default="celsius",
        help="Temperature unit",
    )

    fct = sub.add_parser("forecast", help="Get multi-day weather forecast")
    fct.add_argument("--location", required=True, help="City or place name")
    fct.add_argument("--days", type=int, default=3, help="Forecast days (1-7)")
    fct.add_argument(
        "--unit",
        choices=["celsius", "fahrenheit"],
        default="celsius",
        help="Temperature unit",
    )

    args = parser.parse_args()

    from proxi.mcp.servers.weather_tools import WeatherTools

    wt = WeatherTools()

    if args.cmd == "current":
        result = asyncio.run(wt.get_current_weather(args.location, args.unit))
    else:
        result = asyncio.run(wt.get_forecast(args.location, args.days, args.unit))

    print(json.dumps(result))
    sys.exit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()
