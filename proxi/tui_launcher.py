"""Launcher for the Ink TUI: ensures the gateway is running, then spawns the
Node.js TUI which connects to the gateway over SSE (not the bridge subprocess).
"""

import os
import sys
import subprocess
from pathlib import Path

from proxi.gateway.config import GatewayConfig, GatewayConfigError
from proxi.gateway.daemon import ensure_running, _gateway_url


def _apply_tui_session_from_gateway_yml(env: dict[str, str]) -> None:
    """If ``sources.tui`` disables the startup picker, set ``PROXI_SESSION_ID`` for cli_ink."""
    if env.get("PROXI_SESSION_ID", "").strip():
        return
    home = env.get("PROXI_HOME", "").strip()
    workspace = Path(home).expanduser().resolve() if home else Path.home() / ".proxi"
    try:
        cfg = GatewayConfig.load(workspace)
    except GatewayConfigError:
        return
    tui = cfg.sources.get("tui")
    if tui is None or tui.pick_agent_at_startup:
        return
    if not tui.target_agent:
        return
    agent = cfg.agents.get(tui.target_agent)
    if agent is None:
        return
    session_name = tui.target_session or agent.default_session
    env["PROXI_SESSION_ID"] = f"{agent.agent_id}/{session_name}"


def main() -> None:
    # Ensure the gateway daemon is up before launching the TUI
    try:
        ensure_running(timeout=15.0)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Resolve cli_ink: project root is parent of proxi package
    proxi_root = Path(__file__).resolve().parent
    project_root = proxi_root.parent
    cli_ink = project_root / "cli_ink"
    if not cli_ink.is_dir():
        print("cli_ink not found. Run from project root.", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()

    # Tell the TUI where the gateway lives
    env["PROXI_GATEWAY_URL"] = _gateway_url()
    _apply_tui_session_from_gateway_yml(env)

    # Keep PYTHONPATH so the bridge can still be imported if needed
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    os.chdir(cli_ink)
    use_shell = sys.platform == "win32"

    if (cli_ink / "node_modules").is_dir():
        cmd = "npm run dev" if use_shell else ["npm", "run", "dev"]
        ret = subprocess.call(cmd, env=env, cwd=str(cli_ink), shell=use_shell)
    else:
        cmd = "npx tsx src/index.tsx" if use_shell else ["npx", "tsx", "src/index.tsx"]
        ret = subprocess.call(cmd, env=env, cwd=str(cli_ink), shell=use_shell)
    sys.exit(ret if ret is not None else 0)
