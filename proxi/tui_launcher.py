"""Launcher for the Ink TUI: spawns the Node.js TUI with the Python bridge on PATH."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    # Resolve cli_ink: project root is parent of proxi package
    proxi_root = Path(__file__).resolve().parent
    project_root = proxi_root.parent
    cli_ink = project_root / "cli_ink"
    if not cli_ink.is_dir():
        print("cli_ink not found. Run from project root.", file=sys.stderr)
        sys.exit(1)

    # Ensure the bridge is invoked with the same Python and can find proxi
    bridge_bin = f"{sys.executable} -m proxi.bridge"
    env = os.environ.copy()
    env["PROXI_BRIDGE_BIN"] = bridge_bin
    # So the bridge child process can import proxi when cwd is cli_ink
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    # Prefer npm run dev (uses tsx), else npx tsx
    os.chdir(cli_ink)
    if (cli_ink / "node_modules").is_dir():
        ret = subprocess.call(
            ["npm", "run", "dev"],
            env=env,
            cwd=str(cli_ink),
        )
    else:
        ret = subprocess.call(
            ["npx", "tsx", "src/index.tsx"],
            env=env,
            cwd=str(cli_ink),
        )
    sys.exit(ret if ret is not None else 0)
