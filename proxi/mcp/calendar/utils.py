from __future__ import annotations
from typing import Tuple
import subprocess

def run_osascript(script: str, timeout_s: int = 10) -> Tuple[int, str, str]:
    p = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def esc_applescript(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')