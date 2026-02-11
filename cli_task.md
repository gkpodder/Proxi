The Cursor "Proxi CLI" Master Prompt
Task: Build a High-Fidelity "Claude Code" Style TUI for 'proxi' Agent

I am building an agent called proxi. I need a premium terminal interface built with Ink (React for CLI) that acts as a frontend for my existing Python agent loop.

1. Architecture: The Python-to-Node Bridge
Frontend (Node/TS): Build an Ink-based TUI in a /cli_ink directory.

Backend (Python): Modify my core agent loop to operate in "headless mode," communicating via JSON-RPC over stdin/stdout.

Launcher: Create a root-level bin/proxi (or similar) that spawns the Node.js TUI process, which in turn spawns the Python backend as a child process.

2. UI & Component Requirements
Interactive Chat: A scrollable main window using ink-text-input. Support multi-line input and command history.

Token Streaming: Render LLM responses token-by-token in real-time as they arrive from the Python bridge.

Dynamic Status Bar: A fixed area at the bottom (above the input) that displays:

Active Tool/MCP: "🛠️ Running: [Tool Name]..."

Subagent Status: "🤖 Subagent [Name] is thinking..."

Progress: A loading spinner (use ink-spinner).

Human-in-the-Loop (HITL) Forms: Implement a component that can swap the input field for a Select Menu or Confirmation Toggle (Y/N) whenever the Python backend sends a "request_input" event.

3. Communication Protocol (JSON Schema)
Implement a listener in the TUI for these message types from Python:

{ "type": "text_stream", "content": "..." } – Partial LLM tokens.

{ "type": "status_update", "label": "...", "status": "running|done" } – For Tools/MCPs.

{ "type": "user_input_required", "method": "select|confirm|text", "options": [] } – To trigger TUI forms.

4. Deliverables
cli/package.json: Include ink, react, ink-text-input, ink-spinner, and zod for schema validation.

cli/App.tsx: The main TUI logic using React hooks to manage the agent's state.

proxi/bridge.py: A wrapper for my existing agent loop that captures print statements and emits the JSON-RPC messages instead.

pyproject.toml / setup.py: Configure the proxi entry point to launch this entire stack.

Goal: Focus on making the UI feel snappy and responsive. Ensure that streaming text doesn't cause the screen to flicker and that the status bar stays anchored to the bottom.

Make any necessary changes needed to integrate the proxy agent with this cli.