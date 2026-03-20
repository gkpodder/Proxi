"""CLI entry point for gateway daemon management.

Usage:
    proxi-gateway-ctl start   — start daemon in background
    proxi-gateway-ctl stop    — send SIGTERM to daemon
    proxi-gateway-ctl status  — print health + lane info
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from proxi.gateway.daemon import is_running, start_daemon, stop_daemon, status


def main() -> None:
    parser = argparse.ArgumentParser(description="Proxi gateway daemon control")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("start", help="Start the gateway daemon")
    sub.add_parser("stop", help="Stop the gateway daemon")
    sub.add_parser("status", help="Show gateway status")
    args = parser.parse_args()

    if args.command == "start":
        pid = start_daemon()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if is_running(timeout=0.5):
                print(f"Gateway started (pid {pid})")
                break
            time.sleep(0.3)
        else:
            print(
                f"Gateway started (pid {pid}) but did not become healthy in time.",
                file=sys.stderr,
            )
            sys.exit(1)

    elif args.command == "stop":
        ok = stop_daemon()
        if ok:
            print("Gateway stop signal sent.")
        else:
            print("No gateway PID file found.", file=sys.stderr)
            sys.exit(1)

    elif args.command == "status":
        info = status()
        print(json.dumps(info, indent=2))

    else:
        parser.print_help()
        sys.exit(1)
