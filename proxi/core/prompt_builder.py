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

import hashlib
import json
from pathlib import Path
from typing import Sequence

from proxi.core.state import AgentState, Message
from proxi.llm.schemas import ToolSpec
from proxi.security.key_store import get_user_profile, resolve_db_path


class PromptPayload:
    """Structured prompt payload consumed by LLM clients."""

    def __init__(self, messages: list[Message], system: str | None):
        self.messages = messages
        self.system = system


class PromptBuilder:
    """Builds prompts following the Static→Incremental structure."""

    def __init__(self) -> None:
        self._cached_key: str | None = None
        self._cached_system_prefix: str | None = None

    def build(
        self,
        state: AgentState,
        tools: Sequence[ToolSpec] | None = None,
        deferred_tool_count: int = 0,
        deferred_specs: Sequence[ToolSpec] | None = None,
    ) -> PromptPayload:
        """Build a PromptPayload from agent state and tools.

        Messages are passed through unmodified to preserve prompt-cache
        stability.  Workspace context (plan/todos) is NOT injected here;
        the agent pulls it on demand via tool calls.

        Args:
            state: Current agent state.
            tools: Live tool specs to include in the system prefix.
            deferred_tool_count: Number of tools currently in the deferred
                tier.  When non-zero, a hint is appended to the system prefix
                instructing the LLM to call ``search_tools`` to load them.
            deferred_specs: Lightweight stubs for deferred tools rendered in
                the system prompt so the LLM knows what is available on demand.
        """
        workspace = state.workspace

        system_prefix = None
        if workspace is not None:
            system_prefix = self._get_cached_system_prefix(
                workspace, tools or [], deferred_tool_count, deferred_specs or []
            )

        if not state.history:
            return PromptPayload(messages=[], system=system_prefix)

        return PromptPayload(messages=list(state.history), system=system_prefix)

    # --- Internal helpers -------------------------------------------------

    def _get_cached_system_prefix(
        self,
        workspace,
        tools: Sequence[ToolSpec],
        deferred_tool_count: int = 0,
        deferred_specs: Sequence[ToolSpec] | None = None,
    ) -> str:
        """Build system prefix with a cache keyed by workspace, tools, and deferred count."""
        key = self._system_prefix_cache_key(workspace, tools, deferred_tool_count, deferred_specs or [])
        if self._cached_key == key and self._cached_system_prefix is not None:
            return self._cached_system_prefix
        rendered = self._build_system_prefix(workspace, tools, deferred_tool_count, deferred_specs or [])
        self._cached_key = key
        self._cached_system_prefix = rendered
        return rendered

    def _system_prefix_cache_key(
        self,
        workspace,
        tools: Sequence[ToolSpec],
        deferred_tool_count: int = 0,
        deferred_specs: Sequence[ToolSpec] | None = None,
    ) -> str:
        """Deterministic cache key that invalidates on file/tool changes."""
        global_path = Path(workspace.global_system_prompt_path)
        soul_path = Path(workspace.soul_path)
        db_path = resolve_db_path()
        user_md_path = Path(workspace.workspace_root) / "memory" / "USER.md"
        global_mtime = global_path.stat().st_mtime_ns if global_path.exists() else 0
        soul_mtime = soul_path.stat().st_mtime_ns if soul_path.exists() else 0
        db_mtime = db_path.stat().st_mtime_ns if db_path.exists() else 0
        user_md_mtime = user_md_path.stat().st_mtime_ns if user_md_path.exists() else 0
        tools_shape = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in sorted(tools, key=lambda t: t.name)
        ]
        deferred_stubs = [
            {"name": s.name, "description": s.description}
            for s in sorted(deferred_specs or [], key=lambda s: s.name)
        ]
        payload = {
            "agent_id": workspace.agent_id,
            "global_system_prompt_path": str(global_path),
            "global_mtime_ns": global_mtime,
            "soul_path": str(soul_path),
            "soul_mtime_ns": soul_mtime,
            "db_path": str(db_path),
            "db_mtime_ns": db_mtime,
            "user_md_mtime_ns": user_md_mtime,
            "tools": tools_shape,
            "deferred_tool_count": deferred_tool_count,
            "deferred_stubs": deferred_stubs,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_system_prefix(
        self,
        workspace,
        tools: Sequence[ToolSpec],
        deferred_tool_count: int = 0,
        deferred_specs: Sequence[ToolSpec] | None = None,
    ) -> str:
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

        live_tools_line = ""
        if tools:
            names = ", ".join(t.name for t in sorted(tools, key=lambda t: t.name))
            live_tools_line = f"LIVE TOOLS (call directly): {names}"

        user_profile_text = self._build_user_profile_context()
        user_model_text = self._build_user_model_context(workspace)

        parts = []
        if global_text:
            parts.append(global_text.strip())
        if soul_text:
            parts.append("YOUR IDENTITY:\n" + soul_text.strip())
        if user_model_text:
            parts.append(user_model_text)
        if live_tools_line:
            parts.append(live_tools_line)
        if user_profile_text:
            parts.append(user_profile_text)
        if deferred_tool_count > 0:
            stubs_lines = ""
            if deferred_specs:
                stubs_lines = "\n".join(
                    f"  - {s.name}"
                    for s in sorted(deferred_specs, key=lambda s: s.name)
                )
                stubs_lines = "\nAVAILABLE ON DEMAND:\n" + stubs_lines + "\n"
            parts.append(
                f"## call_tool — {deferred_tool_count} additional tool(s) available on demand\n"
                f"{stubs_lines}\n"
                "To use any tool from the AVAILABLE ON DEMAND list above, call:\n"
                "  call_tool(tool_name=\"<exact name>\", args={{...}})\n\n"
                "call_tool will execute the tool if the name matches, or return the correct schema "
                "and suggestions if the name is wrong or args are missing — retry based on what it returns.\n\n"
                "Rules:\n"
                "- ONLY use tool names from the AVAILABLE ON DEMAND list above. NEVER invent or guess names.\n"
                "- Do NOT call deferred tool names directly — they are not in your live tools list.\n"
                "- Do NOT call unrelated live tools (mcp_read_emails, etc.) before call_tool.\n"
                "- Do NOT use read/list tools to perform write/send actions.\n\n"
                "Examples:\n"
                "- List Obsidian notes → call_tool('mcp_obsidian_list_notes', {})\n"
                "- Create Obsidian note → call_tool('mcp_obsidian_create_note', {\"note_path\": \"Jokes/Funny.md\", \"content\": \"...\"})\n"
                "- Send email → call_tool('mcp_send_email', {\"to\": \"...\", \"subject\": \"...\", \"body\": \"...\"})\n"
                "- Create calendar event → call_tool('mcp_calendar_create_event', {\"summary\": \"...\", \"start\": \"...\", \"end\": \"...\"})\n"
                "- Create Notion page → call_tool('mcp_notion_create_page', {\"title\": \"...\", \"content\": \"...\"})"
            )

        return "\n\n".join(parts).strip()

    def _build_user_model_context(self, workspace) -> str:
        """Read USER.md from the memory directory and return formatted context."""
        try:
            workspace_root = Path(workspace.workspace_root)
            user_md = workspace_root / "memory" / "USER.md"
            if not user_md.exists():
                return ""
            content = user_md.read_text(encoding="utf-8").strip()
            if not content:
                return ""
            # Only inject if there's actual content beyond the section headers
            non_empty = any(
                line.strip() and not line.startswith("##")
                for line in content.splitlines()
            )
            if not non_empty:
                return ""
            return "USER MODEL (learned preferences and conventions):\n" + content
        except Exception:
            return ""

    def _build_user_profile_context(self) -> str:
        """Render user profile context for system prompt when configured."""
        try:
            record = get_user_profile()
        except Exception:
            return ""

        if not record:
            return ""

        profile = record.profile
        if not isinstance(profile, dict):
            return ""

        lines: list[str] = []
        ordered_fields: list[tuple[str, str]] = [
            ("name", "Name"),
            ("location", "Location"),
            ("timezone", "Timezone (IANA format: e.g., America/Toronto)"),
            ("age", "Age"),
            ("occupation", "Occupation"),
            ("email", "Email"),
            ("email_signature", "Preferred Email Signature"),
            ("demographics", "Additional Demographics"),
        ]

        for key, label in ordered_fields:
            value = profile.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    lines.append(f"- {label}: {cleaned}")
            elif isinstance(value, int):
                lines.append(f"- {label}: {value}")

        if not lines:
            return ""

        result = (
            "USER PROFILE CONTEXT:\n"
            + "\n".join(lines)
            + "\nUse this profile only when relevant to the user request "
            "(for example email drafts, signatures, or timezone-aware suggestions). "
            "Timezone is in IANA format (e.g., America/Toronto) — use directly with calendar and weather operations."
        )
        return result

