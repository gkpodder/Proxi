"""Launch the React frontend against an already-running gateway."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

from proxi.gateway.daemon import _gateway_url, is_running


def _frontend_port() -> int:
    return int(os.environ.get("PORT", 5174))


def _frontend_already_running() -> bool:
    """Return True if the frontend server is already answering on its port."""
    port = _frontend_port()
    try:
        r = httpx.get(f"http://localhost:{port}/", timeout=1.0)
        return r.status_code < 500
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


def main() -> None:
    if not is_running(timeout=1.0):
        print(f"Gateway is not reachable at {_gateway_url()}. Start it first.", file=sys.stderr)
        sys.exit(1)

    port = _frontend_port()
    if _frontend_already_running():
        print(f"React frontend is already running at http://localhost:{port}")
        sys.exit(0)

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
    proc = subprocess.Popen(command, cwd=str(frontend_dir), env=env)
    try:
        ret = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        ret = 0
    sys.exit(ret)
