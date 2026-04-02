"""Launch the Discord relay against an already-running gateway."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from proxi.gateway.daemon import _gateway_url, is_running


def main() -> None:
    if not is_running(timeout=1.0):
        print(f"Gateway is not reachable at {_gateway_url()}. Start it first.", file=sys.stderr)
        sys.exit(1)

    project_root = Path(__file__).resolve().parents[1]
    relay_dir = project_root / "discord_relay"
    if not relay_dir.is_dir():
        print("discord_relay not found. Run from project root.", file=sys.stderr)
        sys.exit(1)

    node = shutil.which("node")
    if not node:
        print("Node.js is required to run the Discord relay.", file=sys.stderr)
        sys.exit(1)

    entrypoint = relay_dir / "src" / "index.js"
    if not entrypoint.exists():
        print(f"Discord relay entrypoint not found: {entrypoint}", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    env.setdefault("PROXI_GATEWAY_URL", _gateway_url())

    command = [node, str(entrypoint)]
    proc = subprocess.Popen(command, cwd=str(relay_dir), env=env)
    try:
        ret = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        ret = 0
    sys.exit(ret if ret is not None else 0)
