"""Launch the React frontend against an already-running gateway."""

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
    frontend_dir = project_root / "react_frontend"
    if not frontend_dir.is_dir():
        print("react_frontend not found. Run from project root.", file=sys.stderr)
        sys.exit(1)

    node = shutil.which("node")
    if not node:
        print("Node.js is required to run the React frontend.", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    env.setdefault("PROXI_GATEWAY_URL", _gateway_url())

    command = [node, "server.js"]
    ret = subprocess.call(command, cwd=str(frontend_dir), env=env)
    sys.exit(ret if ret is not None else 0)
