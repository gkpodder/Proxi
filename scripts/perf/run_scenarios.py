"""Run baseline performance scenarios for Proxi internals."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_S = 300


def _sample_process(pid: int, stop_event: threading.Event, out: list[dict[str, float]]) -> None:
    """Sample process CPU and RSS via `ps`."""
    while not stop_event.is_set():
        try:
            proc = subprocess.run(
                ["ps", "-o", "%cpu=,rss=", "-p", str(pid)],
                check=True,
                capture_output=True,
                text=True,
            )
            parts = proc.stdout.strip().split()
            if len(parts) == 2:
                out.append(
                    {
                        "ts": time.time(),
                        "cpu_percent": float(parts[0]),
                        "rss_kb": float(parts[1]),
                    }
                )
        except Exception:
            pass
        stop_event.wait(0.5)


def _run_cli_task(task: str, provider: str, use_mcp: bool, timeout_s: int) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PROXI_PERF_ENABLED", "1")
    env.setdefault("LOG_LEVEL", "INFO")
    agent_id = os.getenv("PROXI_PERF_AGENT_ID", "proxi")
    cmd = [
        sys.executable,
        "-m",
        "proxi.cli.main",
        task,
        "--provider",
        provider,
        "--max-turns",
        "20",
        "--agent-id",
        agent_id,
    ]
    if not use_mcp:
        cmd.append("--no-mcp")
    start = time.time()
    proc = subprocess.Popen(cmd, env=env)
    samples: list[dict[str, float]] = []
    stop_event = threading.Event()
    sampler = threading.Thread(target=_sample_process, args=(proc.pid, stop_event, samples), daemon=True)
    sampler.start()
    try:
        rc = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = 124
    finally:
        stop_event.set()
        sampler.join(timeout=1.0)
    return {
        "exit_code": rc,
        "duration_s": round(time.time() - start, 3),
        "resource_samples": samples,
        "task": task,
    }


def run_scenario(scenario: str, provider: str, use_mcp: bool, timeout_s: int) -> dict[str, Any]:
    if scenario == "S1":
        task = "Give a concise 2-step plan for organizing a study session."
        return _run_cli_task(task, provider, use_mcp=False, timeout_s=timeout_s)
    if scenario == "S2":
        task = (
            "Use tools to list current directory and read README.md if present, "
            "then provide summary in 3 bullets."
        )
        return _run_cli_task(task, provider, use_mcp=False, timeout_s=timeout_s)
    if scenario == "S3":
        task = "Use available MCP tools to fetch lightweight information and summarize results."
        return _run_cli_task(task, provider, use_mcp=use_mcp, timeout_s=timeout_s)
    raise ValueError(f"Unsupported scenario: {scenario}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Proxi perf scenarios")
    parser.add_argument("--scenario", required=True, choices=["S1", "S2", "S3"])
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--mcp", action="store_true", help="Enable MCP for S3")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--output", type=str, default="logs/perf_scenario_result.json")
    args = parser.parse_args()

    result = run_scenario(args.scenario, args.provider, args.mcp, args.timeout)
    payload = {
        "timestamp": time.time(),
        "scenario": args.scenario,
        "provider": args.provider,
        "mcp_enabled": args.mcp,
        "result": result,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
