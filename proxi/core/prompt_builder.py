"""PromptBuilder: assemble static→incremental→volatile prompt structure.

This centralises how prompts are constructed so that:

1. **System Prefix (STATIC)** stays byte-identical across turns when possible:
   - global/system_prompt.md
   - agents/<agent_id>/Soul.md
   - Deterministic textual tool definitions
2. **Chat History (INCREMENTAL)** is the sequence of prior messages.
3. **Workspace Context (VOLATILE)** for the current session (plan.md, todos.md)
   is injected only into the *content of the final user message*.
4. **Current Request (LIVE)** is the newest user content, at the tail of history.
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
    """Builds prompts following the Static→Incremental→Volatile structure."""

    def build(self, state: AgentState, tools: Sequence[ToolSpec] | None = None) -> PromptPayload:
        """Build a PromptPayload from agent state and tools."""
        workspace = state.workspace

        system_prefix = None
        if workspace is not None:
            system_prefix = self._build_system_prefix(workspace, tools or [])

        # Rebuild messages so that only the *last* user message content is
        # augmented with workspace context; all earlier messages remain byte-stable.
        if not state.history:
            return PromptPayload(messages=[], system=system_prefix)

        base_messages = list(state.history)

        # Compute workspace context block (plan/todos) if present.
        workspace_block = ""
        if workspace is not None:
            workspace_block = self._build_workspace_block(
                plan_path=Path(workspace.plan_path),
                todos_path=Path(workspace.todos_path),
            )

        # Only modify the *final* user message; do not inject new messages in between.
        modified_messages: list[Message] = []
        *prefix, last = base_messages
        modified_messages.extend(prefix)

        if last.role == "user" and workspace_block:
            # Inject workspace context at the top of the last user message content.
            original_content = last.content or ""
            new_content = (
                f"{workspace_block}\n\n{original_content}".strip()
                if original_content
                else workspace_block
            )
            modified_messages.append(
                Message(
                    role="user",
                    content=new_content,
                    name=last.name,
                    tool_call_id=last.tool_call_id,
                    tool_calls=last.tool_calls,
                )
            )
        else:
            modified_messages.append(last)

        return PromptPayload(messages=modified_messages, system=system_prefix)

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

        parts = []
        if global_text:
            parts.append(global_text.strip())
        if soul_text:
            parts.append("YOUR IDENTITY:\n" + soul_text.strip())
        if tools_block:
            parts.append(tools_block)

        return "\n\n".join(parts).strip()

    def _build_workspace_block(self, plan_path: Path, todos_path: Path) -> str:
        """Build the volatile workspace context block from plan/todos."""
        plan_text = ""
        todos_text = ""

        try:
            if plan_path.exists():
                plan_text = plan_path.read_text(encoding="utf-8").strip()
        except Exception:
            plan_text = ""

        try:
            if todos_path.exists():
                todos_text = todos_path.read_text(encoding="utf-8").strip()
        except Exception:
            todos_text = ""

        if not plan_text and not todos_text:
            return ""

        parts: list[str] = ["## CURRENT WORKSPACE CONTEXT"]

        if plan_text:
            parts.append("### PLAN")
            parts.append("<workspace_plan>")
            parts.append(plan_text)
            parts.append("</workspace_plan>")

        if todos_text:
            parts.append("### TODOS")
            parts.append("<workspace_todos>")
            parts.append(todos_text)
            parts.append("</workspace_todos>")

        parts.append("--- END WORKSPACE CONTEXT ---")
        return "\n".join(parts)

