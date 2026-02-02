
# Proxi MCPs – Weather + Calendar + Hub (macOS) – Full Functional Set

This bundle includes:
- **Weather MCP**: "all user features" through a reliable backend + best-effort Weather.app UI actions.
- **Calendar MCP**: AppleScript-driven CRUD + search + upcoming + free-slots.
- **Hub MCP**: cross-talk tools (weather-aware scheduling / rescheduling).

## Reality check (important)
- Calendar.app has a real automation dictionary → most features can be automated reliably.
- Weather.app has no stable AppleScript API → **full UI control is not guaranteed**.
  - We provide best-effort UI actions (open, show/search, add/remove location).
  - Everything else is implemented reliably as backend features (like a user would use the app):
    - saved locations, units, home location
    - current/hourly/daily forecasts, feels-like, wind, precipitation, snowfall
    - alerts + driving/outdoor risk at a specific time
    - best-time suggestion within a time window

CLI files are for **your testing only** (they call `impl.py` directly).
Your teammate’s orchestrator should call the MCP **servers**.

## Install
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run servers
```bash
python -m mcp_weather.server
python -m mcp_calendar.server
python -m mcp_hub.server
```

## Test (CLI)
Weather:
```bash
python -m mcp_weather.cli open_weather_app
python -m mcp_weather.cli add_location Toronto --also_open_app
python -m mcp_weather.cli current Toronto
python -m mcp_weather.cli risk Toronto "2026-02-03 11:00:00" driving
python -m mcp_weather.cli best_time Toronto driving "2026-02-03 08:00:00" "2026-02-03 14:00:00"
```

Calendar:
```bash
python -m mcp_calendar.cli open_calendar_app
python -m mcp_calendar.cli upcoming --days 7
python -m mcp_calendar.cli create "Drive to Toronto" "2026-02-03 11:00:00" "2026-02-03 11:45:00" --location Toronto
python -m mcp_calendar.cli free_slots 2026-02-03 --duration 45
```

Hub:
```bash
python -m mcp_hub.cli schedule_drive_if_safe Toronto "2026-02-03 11:00:00" 45 --title "Drive to Toronto"
```

## macOS permissions
- System Settings → Privacy & Security → Accessibility → enable Terminal/IDE (for Weather UI)
- Calendar automation will prompt “Terminal wants to control Calendar” on first run


## Human-like chat testing (OpenAI)
1) Put your key in `.env`:
```
OPENAI_API_KEY=sk-...
# optional:
OPENAI_MODEL=gpt-4.1-mini
```

2) Run natural language requests:
```bash
python chat_cli.py "hey whats the weather in Hong Kong" --pretty
python chat_cli.py "open the weather app and show Hong Kong" --pretty
python chat_cli.py "add Tokyo to my weather app" --pretty
python chat_cli.py "what's the forecast hourly in Toronto for the next 48 hours" --pretty
python chat_cli.py "if it is not snowing at 11 add a drive to Toronto in my calendar" --pretty
```

Tip: use `--dry_run` to only see what tools it would call:
```bash
python chat_cli.py "schedule a drive to Toronto tomorrow at 11 if weather is ok" --dry_run --pretty
```


### Human-friendly output
For demos, print a natural response instead of raw JSON:
```bash
python chat_cli.py "hey whats the weather in Hong Kong" --human
python chat_cli.py "if it is not snowing at 11 add a drive to Toronto in my calendar" --human
```

Tip: you can still see the tool plan and raw JSON by omitting `--human` and using `--pretty`.


(Updated in patched_v3: fixed chat_cli execution logic; it now executes actions unless --dry_run is specified.)
