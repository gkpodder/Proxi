"""Aggregate Proxi perf events from log files."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

EVENT_RE = re.compile(r"\[(?P<event>PERF_[A-Z_]+)\]\s+\[[A-Z]+\]\s+(?P<fields>.*)$")
FIELD_RE = re.compile(r"([a-zA-Z0-9_]+)=([^=]+?)(?=\s+[a-zA-Z0-9_]+=|$)")


def _parse_fields(raw: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in FIELD_RE.findall(raw):
        value = value.strip()
        if value in {"True", "False"}:
            fields[key] = value == "True"
            continue
        try:
            if "." in value:
                fields[key] = float(value)
            else:
                fields[key] = int(value)
            continue
        except ValueError:
            pass
        fields[key] = value
    return fields


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * q
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return sorted_vals[int(idx)]
    frac = idx - low
    return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


def _percentiles(values: list[float]) -> dict[str, float]:
    return {
        "count": float(len(values)),
        "p50": round(_quantile(values, 0.50), 3),
        "p95": round(_quantile(values, 0.95), 3),
        "p99": round(_quantile(values, 0.99), 3),
    }


def collect(logs_dir: Path) -> dict[str, Any]:
    streams: dict[str, list[float]] = defaultdict(list)
    counters: dict[str, int] = defaultdict(int)
    bridge_types: dict[str, int] = defaultdict(int)

    for log_file in logs_dir.glob("**/proxi.log"):
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            match = EVENT_RE.search(line)
            if not match:
                continue
            event = match.group("event").lower()
            fields = _parse_fields(match.group("fields"))
            counters[f"events.{event}"] += 1

            if event == "perf_turn":
                streams["loop.total_ms"].append(float(fields.get("total_ms", 0.0)))
                streams["loop.decide_ms"].append(float(fields.get("decide_ms", 0.0)))
                streams["loop.act_ms"].append(float(fields.get("act_ms", 0.0)))
                streams["loop.observe_ms"].append(float(fields.get("observe_ms", 0.0)))
                streams["loop.reflect_ms"].append(float(fields.get("reflect_ms", 0.0)))
            elif event == "perf_tool_exec":
                streams["tool.exec_ms"].append(float(fields.get("elapsed_ms", 0.0)))
                if not fields.get("success", True):
                    counters["tool.failures"] += 1
            elif event in {"perf_subagent_exec", "perf_subagent_manager"}:
                streams["subagent.exec_ms"].append(float(fields.get("elapsed_ms", 0.0)))
                if fields.get("timeout", False):
                    counters["subagent.timeouts"] += 1
            elif event == "perf_mcp_request":
                streams["mcp.request_ms"].append(float(fields.get("elapsed_ms", 0.0)))
                status = str(fields.get("status", "unknown"))
                counters[f"mcp.status.{status}"] += 1
            elif event == "perf_bridge_queue_wait":
                streams["bridge.queue_wait_ms"].append(float(fields.get("wait_ms", 0.0)))
                streams["bridge.queue_depth"].append(float(fields.get("depth", 0.0)))
            elif event == "perf_bridge_emit":
                streams["bridge.emit_ms"].append(float(fields.get("elapsed_ms", 0.0)))
                streams["bridge.msg_bytes"].append(float(fields.get("bytes", 0.0)))
                bridge_types[str(fields.get("msg_type", "unknown"))] += 1
            elif event == "perf_history_write":
                streams["state.history_write_ms"].append(float(fields.get("elapsed_ms", 0.0)))
            elif event == "perf_api_log":
                streams["api.log_ms"].append(float(fields.get("elapsed_ms", 0.0)))

    percentiles = {name: _percentiles(vals) for name, vals in streams.items()}
    return {
        "logs_dir": str(logs_dir),
        "percentiles": percentiles,
        "counters": dict(counters),
        "bridge_message_types": dict(bridge_types),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate perf metrics from Proxi logs")
    parser.add_argument("--logs-dir", type=str, default="logs")
    parser.add_argument("--output", type=str, default="logs/perf_baseline.json")
    args = parser.parse_args()

    data = collect(Path(args.logs_dir))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
