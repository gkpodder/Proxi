# Proxi

Developer Names: Gourob, Ajay, Aman, Savinay

Date of project start: Sep. 15 2025

## Project Description
This project is an AI-powered assistive technology platform designed to make computers more accessible for individuals who face barriers with traditional interfaces, such as people with disabilities, elderly users, or those unfamiliar with digital devices.
At its core, the system combines speech recognition, natural language understanding, and text-to-speech to allow users to control and interact with a computer entirely through their voice. Instead of navigating menus, using a mouse, or typing, users can simply speak naturally to the system, which responds with clear, human-like speech.

## User Guide Video
https://www.youtube.com/watch?v=vR8O_09WrnM

## Core Loop Architecture

Proxi follows a three-layer architecture:

```
User Goal
   ↓
Primary Agent (Planner / Orchestrator)
   ↓
┌──────────────┬──────────────┬──────────────┬─────────────────────────┐
│   Tools      │   MCPs       │  Sub-Agents  │ show_collaborative_form │
│ (stateless)  │ (external)   │ (stateful)   │  (human-in-the-loop)    │
└──────────────┴──────────────┴──────────────┴─────────────────────────┘
```

The agent loop follows: **REASON → DECIDE → ACT → OBSERVE → REFLECT → LOOP**

Each turn progresses through states: `PENDING` → `DECIDING` → `ACTING` → `OBSERVING` → `REFLECTING` → `COMPLETED`. The **DECIDE** step produces exactly one of:

| Decision Type | Description |
|---------------|-------------|
| `RESPOND` | Communicate with the user (answers, confirmations, clarifications) |
| `TOOL_CALL` | Execute a tool (including MCP tools) |
| `SUB_AGENT_CALL` | Delegate to a specialised sub-agent |
| `REQUEST_USER_INPUT` | Call `show_collaborative_form` when blocked by missing information |

**TUI integration:** The loop emits events via a `BridgeEmitter` (JSON lines to stdout) for streaming text, tool/subagent status, and status updates. When the agent needs structured input, a `FormBridge` sends `user_input_required` to the TUI and awaits `user_input_response` before continuing.

**Workspace context:** Each session is attached to a `WorkspaceConfig` that provides paths for `Soul.md`, `plan.md`, `todos.md`, and `history.jsonl`. Workspace-scoped tools (`manage_plan`, `manage_todos`, `read_soul`) operate on these files.

## Workspace Layout

Proxi uses a filesystem-backed workspace under `~/.proxi/` (or `$PROXI_HOME`):

```
~/.proxi/
├── global/
│   └── system_prompt.md      # Global instructions for all agents
└── agents/
    └── <agent_id>/
        ├── Soul.md           # Agent name and persona
        ├── config.yaml       # (reserved for future use)
        └── sessions/
            └── <session_id>/
                ├── history.jsonl
                ├── plan.md    # Created via manage_plan tool
                └── todos.md   # Created via manage_todos tool
```

On TUI startup, the bridge runs an interactive bootstrap: select an existing agent or create a new one. A single ephemeral session is created per agent. Use `/agent` in the TUI to switch agents.

## Tech Stack

- **Python 3.12+** with UV for build system and package management
- asyncio for async operations
- Pydantic for data validation
- Structlog for structured logging
- **Bun** and **Ink** (React) for the TUI — scrollback-native, no alt-screen

## Installation

**Prerequisites**

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) (install with `curl -LsSf https://astral.sh/uv/install.sh | sh` or your package manager).
- For the **TUI**: **Bun** (see installation instructions at https://bun.sh).

**Steps**

From the project root:

```bash
# Install Python dependencies and register CLI commands
uv sync
```

To use the **interactive TUI**, install the frontend dependencies once with Bun:

```bash
# Install JS dependencies for the Ink TUI
cd cli_ink/
bun install
```

You can run `proxi` via `uv run proxi` (no global install) or, after `uv sync`, use the `proxi` script if your environment has the project’s virtualenv on `PATH`.

## Usage

**API keys** (required for the agent):

Proxi now stores API keys in a local SQLite database at `config/api_keys.db`.

Initialize the table manually (optional, this is run automatically by the React frontend startup scripts):

```bash
uv run python scripts/init_api_keys_db.py
```

Manage keys from the React frontend key manager (`🔐` button in the top bar), or via CLI:

```bash
uv run python -m proxi.security.key_store upsert --key OPENAI_API_KEY --value "your-key-here"
# or
uv run python -m proxi.security.key_store upsert --key ANTHROPIC_API_KEY --value "your-key-here"
```

**Optional environment variables**

| Variable | Description |
|----------|-------------|
| `PROXI_HOME` | Override workspace root (default: `~/.proxi`) |
| `PROXI_WORKING_DIR` | Working directory for the bridge (default: `.`) |
| `PROXI_PROVIDER` | LLM provider: `openai` or `anthropic` (default: `openai`) |
| `PROXI_MAX_TURNS` | Max turns per task (default: `20`) |
| `PROXI_MCP_SERVER` | MCP server command (e.g. `npx:@modelcontextprotocol/server-filesystem /path`) |
| `PROXI_NO_SUB_AGENTS` | Set to `1` to disable sub-agents |

**Interactive TUI (default)**

From the project root:

```bash
proxi
# or
uv run proxi
```

This starts the Ink TUI and the agent bridge so you can chat and run tasks in the terminal. The TUI runs the same agent loop (tools, MCP, sub-agents, collaborative forms) behind the scenes. The bridge communicates with the TUI via JSON lines over stdin/stdout.

**One-shot agent (CLI)**

To run a single task from the command line without the TUI:

```bash
# Using OpenAI (default)
uv run proxi-run "Your task here"

# Using Anthropic
uv run proxi-run --provider anthropic "Your task here"

# With options
uv run proxi-run --max-turns 30 --log-level DEBUG "Your task here"

# With MCP server (filesystem example)
uv run proxi-run --mcp-filesystem "." "List all files in the current directory"

# With custom MCP server
uv run proxi-run --mcp-server "npx:@modelcontextprotocol/server-filesystem /path" "Your task"
```


**TUI features:**

- **Scrollback-native layout** — conversation prints into the terminal's native scrollback buffer; only the status bar and input area are Ink-managed. Preserves native scroll, Cmd+F search, and text selection.
- **Command palette** — type `/` to open. Commands: `/agent` (switch agent), `/mcps` (enable/disable MCPs), `/clear` (clear conversation), `/plan` (view plan.md), `/todos` (view todos.md), `/help`, `/exit`.
- **Collaborative forms** — when the agent calls `show_collaborative_form`, a form overlay appears for structured input (choice, multiselect, yesno, text). Supports `show_if` for conditional questions.
- **Plan / Todos overlay** — `/plan` and `/todos` display the current session's `plan.md` and `todos.md` in an overlay (Esc to close).
- **Agent bootstrap** — on first run (or when no agents exist), you're prompted to create an agent (name, persona). With existing agents, you select one or create new.
- **Input history** — up/down arrows when the input is empty cycle through previous messages.

To run the TUI directly with Bun (without going through the `proxi` CLI wrapper):

```bash
# From project root, using the helper script
bun run proxi-tui

# Or from inside cli_ink/ for development
cd cli_ink
bun run dev        # runs the TUI in watch mode via tsx

# Or run the built CLI
bun run start      # runs: bun run build && bun dist/index.js
```

**Optional verification**

- **Bridge only:** From project root, run `uv run proxi-bridge`. You should see `{"type":"ready"}`. (Ctrl+C to exit.) This checks that the Python agent bridge starts correctly.
- **Full flow:** Run `proxi`; you should see the boot sequence, agent selection (if applicable), and a prompt. Type a task and press Enter.
