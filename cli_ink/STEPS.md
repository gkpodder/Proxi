# TUI + Bridge: Step-by-step verification

Run from the **project root** (the folder that contains `proxi/` and `pyproject.toml`). Set your API key once: `export OPENAI_API_KEY="your-key"`.

---

## Step 1: Bridge works from the shell

**Goal:** The Python bridge starts and prints one line: `{"type":"ready"}`.

1. Open a terminal in the **project root** (e.g. `cd /Users/podderg/Documents/school/Capstone`).
2. Set your API key: `export OPENAI_API_KEY="your-key"`.
3. Run:
   ```bash
   uv run proxi-bridge
   ```
4. You should see **exactly one line**: `{"type":"ready"}`. The process then waits for input.
5. Press **Ctrl+C** to exit.

**If it fails:**  
- "Bridge config error: OPENAI_API_KEY..." → set `export OPENAI_API_KEY="..."` in the same terminal.  
- "ModuleNotFoundError: No module named 'proxi'" → you are not in the project root; `cd` to the folder that contains the `proxi` directory.

---

## Step 2: Minimal TUI starts and shows Ready

**Goal:** The TUI starts, spawns the bridge, and shows "Bridge: Ready" plus an input line.

1. From project root, install TUI deps once:
   ```bash
   cd cli_ink && npm install && cd ..
   ```
2. Run the TUI:
   ```bash
   npm run proxi-tui
   ```
   (This runs `cd cli_ink && npm run dev`.)

3. You should see **"Bridge: Ready"** and a **`>`** prompt. Type a short task (e.g. "Say hi") and press Enter.

**If you stay on "Bridge: Starting..."** check the red error line (e.g. missing API key, or `uv` not found). Ensure Step 1 works first.

---

## Step 3: Full TUI (status bar, chat area)

Same as Step 2; the TUI now also shows a status line when the agent uses tools and a scrollable chat area. No extra verification—if Step 2 works, Step 3 is the same run with more UI.

---

## Step 4: Run from project root only

From project root you can use:

- `npm run proxi-tui` — runs the TUI (after `cd cli_ink && npm install` once)
- `uv run proxi-tui` — Python launcher that runs the TUI with env set

Either way, set `OPENAI_API_KEY` before running.
