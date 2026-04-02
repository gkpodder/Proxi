"""Unified CLI entry point for Proxi."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="proxi",
        description="Proxi – AI agent framework",
    )
    sub = parser.add_subparsers(dest="command")

    # gateway start|stop|restart|status
    gw = sub.add_parser("gateway", help="Manage the gateway daemon")
    gw_sub = gw.add_subparsers(dest="gw_command")
    gw_sub.add_parser("start", help="Start gateway daemon")
    gw_sub.add_parser("stop", help="Stop gateway daemon")
    gw_sub.add_parser("restart", help="Restart gateway daemon")
    gw_sub.add_parser("status", help="Show gateway status (JSON)")

    sub.add_parser("frontend", help="Start React frontend (requires gateway)")
    sub.add_parser("discord", help="Start Discord relay (requires gateway)")

    # run: capture all remaining tokens and forward to cli/main.py
    run_p = sub.add_parser("run", help="Run a one-shot agent task")
    run_p.add_argument("run_args", nargs=argparse.REMAINDER, help="Task and flags (same as proxi-run)")

    # keys: delegate to key_store CLI
    sub.add_parser("keys", help="Manage API keys and MCP settings")

    sub.add_parser("version", help="Print version and exit")

    # Parse only the top-level command so subcommand flags are not consumed here
    args, _ = parser.parse_known_args()

    if args.command is None:
        _cmd_tui()
    elif args.command == "gateway":
        _cmd_gateway(args)
    elif args.command == "frontend":
        _cmd_frontend()
    elif args.command == "discord":
        _cmd_discord()
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "keys":
        _cmd_keys()
    elif args.command == "version":
        _cmd_version()
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_tui() -> None:
    """Start TUI, auto-starting the gateway daemon if not running."""
    from proxi.gateway.daemon import ensure_running, _gateway_url

    if True:  # always attempt to ensure running; is_running is cheap
        try:
            from proxi.gateway.daemon import is_running
            if not is_running(timeout=1.0):
                print(f"Gateway not running at {_gateway_url()}, starting daemon...")
                ensure_running()
        except RuntimeError as exc:
            print(f"Error starting gateway: {exc}", file=sys.stderr)
            sys.exit(1)

    from proxi.tui_launcher import main as tui_main
    tui_main()  # exits via sys.exit internally


def _cmd_gateway(args: argparse.Namespace) -> None:
    import json
    import time

    from proxi.gateway.daemon import (
        ensure_running,
        is_running,
        start_daemon,
        status,
        stop_daemon,
    )

    gc = getattr(args, "gw_command", None)

    if gc == "start":
        pid = start_daemon()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if is_running(timeout=0.5):
                print(f"Gateway started (pid {pid})")
                return
            time.sleep(0.3)
        print("Gateway started but did not become healthy in time.", file=sys.stderr)
        sys.exit(1)

    elif gc == "stop":
        ok = stop_daemon()
        if ok:
            print("Gateway stop signal sent.")
        else:
            print("No gateway PID file found.", file=sys.stderr)
            sys.exit(1)

    elif gc == "restart":
        stop_daemon()
        # Wait up to 5 s for the old process to exit
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not is_running(timeout=0.5):
                break
            time.sleep(0.3)
        print("Restarting gateway...")
        try:
            ensure_running()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print("Gateway restarted.")

    elif gc == "status":
        info = status()
        print(json.dumps(info, indent=2))

    else:
        print("Usage: proxi gateway {start|stop|restart|status}")
        sys.exit(1)


def _cmd_frontend() -> None:
    from proxi.react_launcher import main as react_main
    react_main()


def _cmd_discord() -> None:
    from proxi.discord_relay_launcher import main as discord_main
    discord_main()


def _cmd_run(args: argparse.Namespace) -> None:
    """Delegate to the existing agent CLI, forwarding all captured flags."""
    run_args = getattr(args, "run_args", [])
    sys.argv = [sys.argv[0]] + run_args
    from proxi.cli.main import cli_main
    cli_main()


def _cmd_keys() -> None:
    """Delegate to key_store CLI, stripping the 'keys' token from argv."""
    # sys.argv is e.g. ['proxi', 'keys', 'list', '--show-values']
    # key_store.main() re-parses sys.argv so strip the 'keys' subcommand
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    from proxi.security.key_store import main as keys_main
    raise SystemExit(keys_main())


def _cmd_version() -> None:
    try:
        from importlib.metadata import version
        print(version("proxi"))
    except Exception:
        print("proxi (version unknown)")
