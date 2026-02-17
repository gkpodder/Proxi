# Proxi

Developer Names: Gourob, Ajay, Aman, Savinay

Date of project start: Sep. 15 2025

## Project Description
This project is an AI-powered assistive technology platform designed to make computers more accessible for individuals who face barriers with traditional interfaces, such as people with disabilities, elderly users, or those unfamiliar with digital devices.
At its core, the system combines speech recognition, natural language understanding, and text-to-speech to allow users to control and interact with a computer entirely through their voice. Instead of navigating menus, using a mouse, or typing, users can simply speak naturally to the system, which responds with clear, human-like speech.

## Architecture

Proxi follows a three-layer architecture:

```
User Goal
   ↓
Primary Agent (Planner / Orchestrator)
   ↓
┌──────────────┬──────────────┬──────────────┐
│   Tools      │   MCPs       │  Sub-Agents  │
│ (stateless)  │ (external)   │ (stateful)   │
└──────────────┴──────────────┴──────────────┘
```

## Core Loop

The agent loop follows: **REASON → DECIDE → ACT → OBSERVE → REFLECT → LOOP**

Where ACT can be:
- Tool execution
- MCP call
- Sub-agent invocation

## Development Phases

- **Phase 1**: Single Agent Loop (Tools only)
- **Phase 2**: Sub-Agent Infrastructure
- **Phase 3**: Planner + Specialist Split
- **Phase 4**: Verification & Reflection
- **Phase 5**: Parallelism (Optional)

## Tech Stack

- Python 3.11+
- UV for build system and package management
- asyncio for async operations
- Pydantic for data validation
- Structlog for structured logging
- Bun and Ink for TUI

## Installation

**Prerequisites**

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/) (install with `curl -LsSf https://astral.sh/uv/install.sh | sh` or your package manager).
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
bun install
```

You can run `proxi` via `uv run proxi` (no global install) or, after `uv sync`, use the `proxi` script if your environment has the project’s virtualenv on `PATH`.

## Usage

**API keys** (required for the agent):

```bash
export OPENAI_API_KEY="your-key-here"
# or
export ANTHROPIC_API_KEY="your-key-here"
```

**Interactive TUI (default)**

From the project root:

```bash
proxi
# or
uv run proxi
```

This starts the Ink TUI and the agent bridge so you can chat and run tasks in the terminal. The TUI runs the same agent loop (tools, MCP, sub-agents) behind the scenes.

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

### TUI (Terminal UI)

The **recommended way** to use Proxi interactively is to run **`proxi`** (or `uv run proxi`). That command:

1. Starts the **agent bridge** (Python) in the background.
2. Launches the **Ink TUI** (Bun + Ink/React) so you can type tasks and see responses in a chat-style interface.

**Requirements:** `uv`, Bun, and `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`). Ensure you have run `bun install` at the project root at least once (see [Installation](#installation)).

To run the TUI directly with Bun (without going through the `proxi` CLI wrapper), you can also use:

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
- **Full flow:** Run `proxi`; you should see “Bridge: Ready” and a prompt. Type a task and press Enter.

For step-by-step checks and troubleshooting, see [`cli_ink/STEPS.md`](cli_ink/STEPS.md).

## Project Status

**Phase 1 Complete** ✅
- Core agent loop with REASON → DECIDE → ACT → OBSERVE → REFLECT
- Tool system (filesystem, shell)
- LLM clients (OpenAI, Anthropic)
- State management and memory
- Structured logging and observability
- CLI interface

**Phase 2 Complete** ✅
- Sub-agent infrastructure with registry and manager
- Sub-agent lifecycle management (budgets, timeouts)
- Summarizer sub-agent for testing
- MCP (Model Context Protocol) client and adapters
- Support for real MCP servers (filesystem, GitHub, etc.)
- Integration of sub-agents and MCP into agent loop

**Next Phases** (Not yet implemented)
- Phase 3: Planner + Specialist Split
- Phase 4: Verification & Reflection
- Phase 5: Parallelism

## Phase 2 Features

### Sub-Agents

Sub-agents are now available! They can be invoked by the primary agent to handle specialized tasks.

Example:
```bash
uv run proxi-run "Summarize this long text: [your text here]"
```

The agent will automatically use the summarizer sub-agent when appropriate.

### MCP Support

You can connect to MCP servers to extend proxi's capabilities:

```bash
uv run proxi-run --mcp-server "python:tests/mcp_server_example.py" "Your task"
```

See `tests/README.md` for more information about the test MCP server.
