# Proxi Performance Baseline Harness

This folder contains a lightweight baseline harness for Proxi core internals.

## Scenarios

Use the same repo and environment, then run each scenario to generate logs under `logs/<timestamp>/proxi.log`.

- `S1` conversational: mostly respond turns, minimal tools
- `S2` tool-heavy: repeated filesystem/date tool use and mixed turn actions
- `S3` MCP-heavy: MCP enabled with repeated MCP calls
- `S4` abort/cancel stress: repeated `start/abort/start` against bridge
- `S5` bridge burst traffic: high-frequency status/text events

## Recommended Environment

```bash
export PROXI_PERF_ENABLED=1
export LOG_LEVEL=INFO
```

Optional:

```bash
export PROXI_API_LOG_SAMPLE_RATE=0.25
export PROXI_API_LOG_PRETTY=0
```

## Running Scenario Driver

The driver executes pre-defined scenario prompts and saves a summary file.

```bash
uv run python scripts/perf/run_scenarios.py --scenario S1 --provider openai
uv run python scripts/perf/run_scenarios.py --scenario S2 --provider openai
uv run python scripts/perf/run_scenarios.py --scenario S3 --provider openai --mcp
```

For bridge stress scenarios:

```bash
uv run python scripts/perf/run_scenarios.py --scenario S4 --provider openai
uv run python scripts/perf/run_scenarios.py --scenario S5 --provider openai
```

## Aggregation

After runs complete, aggregate latency and reliability metrics:

```bash
uv run python scripts/perf/aggregate_perf.py --logs-dir logs --output logs/perf_baseline.json
```

The report includes:

- p50/p95/p99 for loop and subsegments (`perf_turn`)
- tool and subagent execution distributions
- queue wait/depth distributions
- MCP timeout/error rates
- bridge message bytes/frequency
- basic CPU/RSS snapshots from scenario runs
