"""Launcher for the Ink TUI: spawns the Node.js TUI with the Python bridge on PATH."""

import os
import shutil
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
    
    # On Windows, we need to use shell=True for command resolution
    use_shell = sys.platform == "win32"
    
    if (cli_ink / "node_modules").is_dir():
        cmd = "npm run dev" if use_shell else ["npm", "run", "dev"]
        ret = subprocess.call(
            cmd,
            env=env,
            cwd=str(cli_ink),
            shell=use_shell,
        )
    else:
        cmd = "npx tsx src/index.tsx" if use_shell else ["npx", "tsx", "src/index.tsx"]
        ret = subprocess.call(
            cmd,
            env=env,
            cwd=str(cli_ink),
            shell=use_shell,
        )
    sys.exit(ret if ret is not None else 0)
