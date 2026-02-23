"""PromptBuilder: assemble static→incremental prompt structure.

This centralises how prompts are constructed so that:

1. **System Prefix (STATIC)** stays byte-identical across turns when possible:
   - global/system_prompt.md
   - agents/<agent_id>/Soul.md
   - Deterministic textual tool definitions
2. **Chat History (INCREMENTAL)** is the sequence of prior messages.

Workspace context (plan.md, todos.md) is NOT injected automatically.
The agent pulls it on demand via manage_plan / manage_todos tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from proxi.core.state import AgentState, Message
from proxi.llm.schemas import ToolSpec


class PromptPayload:
    """Structured prompt payload consumed by LLM clients."""

    def __init__(self, messages: list[Message], system: str | None):
        self.messages = messages
        self.system = system


class PromptBuilder:
    """Builds prompts following the Static→Incremental structure."""

    def build(self, state: AgentState, tools: Sequence[ToolSpec] | None = None) -> PromptPayload:
        """Build a PromptPayload from agent state and tools.

        Messages are passed through unmodified to preserve prompt-cache
        stability.  Workspace context (plan/todos) is NOT injected here;
        the agent pulls it on demand via tool calls.
        """
        workspace = state.workspace

        system_prefix = None
        if workspace is not None:
            system_prefix = self._build_system_prefix(workspace, tools or [])

        if not state.history:
            return PromptPayload(messages=[], system=system_prefix)

        return PromptPayload(messages=list(state.history), system=system_prefix)

    # --- Internal helpers -------------------------------------------------

    def _build_system_prefix(self, workspace, tools: Sequence[ToolSpec]) -> str:
        """Assemble the static system prefix: global + soul + tool definitions."""
        global_text = ""
        soul_text = ""

        try:
            global_path = Path(workspace.global_system_prompt_path)
            if global_path.exists():
                global_text = global_path.read_text(encoding="utf-8")
        except Exception:
            global_text = ""

        try:
            soul_path = Path(workspace.soul_path)
            if soul_path.exists():
                soul_text = soul_path.read_text(encoding="utf-8")
        except Exception:
            soul_text = ""

        tools_block_lines: list[str] = []
        if tools:
            tools_block_lines.append("AVAILABLE TOOLS:")
            for tool in sorted(tools, key=lambda t: t.name):
                tools_block_lines.append(f"- {tool.name}: {tool.description}")
        tools_block = "\n".join(tools_block_lines)

        tool_names = {t.name for t in tools} if tools else set()
        form_guidance = ""
        if "show_collaborative_form" in tool_names:
            form_guidance = """
## show_collaborative_form — When and How to Use

Call `show_collaborative_form` when:
- You need specific information from the user not present in the conversation history
- The missing information would materially change your approach or the output you produce
- You cannot make a reasonable assumption and proceeding without it risks a wrong result

Do NOT call `show_collaborative_form` when:
- You can make a reasonable assumption and state it in your response
- The information is already present in the conversation
- You need minor clarification — use RESPOND to ask conversationally instead
- You want to confirm something trivial

When building the questions array:
- Set `goal` to one sentence: what you are trying to determine
- Set `hint` on each question to a plain-language explanation of why it matters (shown to user)
- Set `why` to your internal reasoning about how the answer affects your next steps (used by Reflector, not shown to user)
- Prefer `yesno` and `choice` over `text` wherever possible
- Keep the question list minimal — only ask what you cannot infer
- Do NOT include an "Other" or custom option in `options` arrays — the TUI adds it automatically
- Do NOT use types "number" or "file" — only "choice", "multiselect", "yesno", "text" are supported
"""

        parts = []
        if global_text:
            parts.append(global_text.strip())
        if soul_text:
            parts.append("YOUR IDENTITY:\n" + soul_text.strip())
        if tools_block:
            parts.append(tools_block)
        if form_guidance:
            parts.append(form_guidance.strip())

        return "\n\n".join(parts).strip()

