"""Gateway daemon lifecycle helpers — start / stop / status."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import shutil

import httpx

from proxi.observability.logging import get_logger
from proxi.workspace import WorkspaceManager

logger = get_logger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


def _runtime_dir() -> Path:
    """Return a writable runtime directory for pid/log files."""
    candidates = [
        Path.home() / ".proxi",
        Path.home() / ".cache" / "proxi",
        Path("/tmp") / "proxi",
    ]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return d
        except OSError:
            continue
    # Last-resort fallback; if this fails too, the caller will see the error.
    return Path("/tmp")


def _pid_file() -> Path:
    env = os.environ.get("PROXI_GATEWAY_PID_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    return _runtime_dir() / "gateway.pid"


def _daemon_log_file() -> Path:
    env = os.environ.get("PROXI_GATEWAY_DAEMON_LOG", "").strip()
    if env:
        return Path(env).expanduser()
    return _runtime_dir() / "gateway-daemon.log"


def _gateway_url() -> str:
    host = os.environ.get("GATEWAY_HOST", DEFAULT_HOST)
    port = int(os.environ.get("GATEWAY_PORT", str(DEFAULT_PORT)))
    return f"http://{host}:{port}"


def is_running(timeout: float = 1.0) -> bool:
    """Check if the gateway daemon is reachable."""
    try:
        r = httpx.get(f"{_gateway_url()}/health", timeout=timeout)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


def _write_pid(pid: int) -> None:
    pid_file = _pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid), encoding="utf-8")


def _read_pid() -> int | None:
    pid_file = _pid_file()
    if pid_file.exists():
        try:
            return int(pid_file.read_text().strip())
        except ValueError:
            return None
    return None


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _gateway_command() -> tuple[list[str], Path | None]:
    """Pick a startup command that includes installed dependencies."""
    project_root = Path(__file__).resolve().parents[2]
    uv_bin = shutil.which("uv")
    if uv_bin and (project_root / "pyproject.toml").exists():
        return [uv_bin, "run", "proxi-gateway"], project_root
    return [sys.executable, "-m", "proxi.gateway.server"], None


def start_daemon() -> int:
    """Start the gateway as a detached background process.  Returns PID."""
    workspace_root = Path(os.environ.get("PROXI_HOME", str(Path.home() / ".proxi"))).expanduser()
    WorkspaceManager(root=workspace_root).ensure_global_system_prompt()

    if is_running():
        pid = _read_pid()
        logger.info("gateway_already_running", pid=pid)
        return pid or 0

    env = os.environ.copy()
    cmd, cwd = _gateway_command()

    # Ensure the key-store DB path is absolute so it resolves regardless of CWD.
    if cwd and "PROXI_KEYS_DB_PATH" not in env:
        candidate = cwd / "config" / "api_keys.db"
        if candidate.exists():
            env["PROXI_KEYS_DB_PATH"] = str(candidate)
    daemon_log = _daemon_log_file()
    daemon_log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = daemon_log.open("ab")
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )
    log_handle.close()
    _write_pid(proc.pid)
    logger.info("gateway_daemon_started", pid=proc.pid, command=" ".join(cmd), log=str(daemon_log))
    return proc.pid


def stop_daemon() -> bool:
    """Send SIGTERM to the daemon.  Returns True if successfully stopped."""
    pid = _read_pid()
    if pid is None:
        logger.info("gateway_no_pid_file")
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("gateway_sigterm_sent", pid=pid)
    except ProcessLookupError:
        logger.info("gateway_process_not_found", pid=pid)
    _pid_file().unlink(missing_ok=True)
    return True


def status() -> dict:
    """Return a dict with gateway status info."""
    running = is_running()
    pid = _read_pid()
    info: dict = {"running": running, "pid": pid, "url": _gateway_url()}
    if running:
        try:
            r = httpx.get(f"{_gateway_url()}/health", timeout=2.0)
            info["health"] = r.json()
        except Exception:
            pass
    return info


def ensure_running(timeout: float = 10.0) -> None:
    """Start the gateway if it is not already running.  Block until healthy."""
    if is_running():
        return
    pid = start_daemon()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(timeout=0.5):
            return
        if pid and not _pid_is_alive(pid):
            log_file = _daemon_log_file()
            tail = ""
            try:
                text = log_file.read_text(encoding="utf-8")
                lines = [ln for ln in text.splitlines() if ln.strip()]
                tail = "\n".join(lines[-12:])
            except OSError:
                pass
            msg = (
                "Gateway process exited before becoming healthy. "
                f"Check daemon log: {log_file}."
            )
            if tail:
                msg += f"\nRecent log output:\n{tail}"
            raise RuntimeError(msg)
        time.sleep(0.3)
    raise RuntimeError(
        f"Gateway did not become healthy within {timeout}s. "
        f"Check daemon log: {_daemon_log_file()}."
    )
