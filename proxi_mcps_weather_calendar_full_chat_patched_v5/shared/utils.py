
from __future__ import annotations
import subprocess
from typing import Tuple

def run_osascript(script: str, timeout_s: int = 25) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"osascript timeout after {timeout_s}s"
    except FileNotFoundError:
        return 127, "", "osascript not found (macOS only)"
    except Exception as e:
        return 1, "", str(e)

def esc_applescript(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\"')
