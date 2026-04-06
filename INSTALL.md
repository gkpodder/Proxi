# Installation

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- [`bun`](https://bun.sh) for the TUI, GUI, and Discord relay dependencies

## Install

From the repository root:

```bash
uv sync
uv run proxi setup
```

The setup script will:

- Install Bun dependencies for `cli_ink`, `react_frontend`, and `discord_relay`
- Initialize or verify `config/api_keys.db`

If you need to repeat setup after pulling changes or repairing a local environment, rerun `uv run proxi setup`.

## Verify

Start the gateway first:

```bash
uv run proxi gateway start
```

Then launch the interface you want:

```bash
uv run proxi
uv run proxi frontend
uv run proxi discord
```

## Uninstall

To remove the local installation, delete the generated environment and dependency folders:

- `.venv`
- `cli_ink/node_modules`
- `react_frontend/node_modules`
- `discord_relay/node_modules`

If you also want to reset local state, delete `config/api_keys.db`.