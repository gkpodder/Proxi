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
│ (stateless)  │ (external)  │ (stateful)   │
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

- Python 3.14+
- UV for build system and package management
- asyncio for async operations
- Pydantic for data validation
- Structlog for structured logging

## Installation

```bash
# Install dependencies using uv
uv sync

# Or install in development mode
uv pip install -e .
```

## Usage

Set up your API key:
```bash
export OPENAI_API_KEY="your-key-here"
# or
export ANTHROPIC_API_KEY="your-key-here"
```

Run the agent:
```bash
# Using OpenAI (default)
uv run proxi "Your task here"

# Using Anthropic
uv run proxi --provider anthropic "Your task here"

# With options
uv run proxi --max-turns 30 --log-level DEBUG "Your task here"

# With MCP server (filesystem example)
uv run proxi --mcp-filesystem "." "List all files in the current directory"

# With custom MCP server
uv run proxi --mcp-server "npx:@modelcontextprotocol/server-filesystem /path" "Your task"
```

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
uv run proxi "Summarize this long text: [your text here]"
```

The agent will automatically use the summarizer sub-agent when appropriate.

### MCP Support

You can connect to MCP servers to extend proxi's capabilities:

```bash
uv run proxi --mcp-server "python:tests/mcp_server_example.py" "Your task"
```

See `tests/README.md` for more information about the test MCP server.



To run Project:
### Terminal 1 - Backend
`uv run python run_server.py`

### Terminal 2 - Frontend  
```
cd frontend
npm run dev
```

