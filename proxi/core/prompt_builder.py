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
        """
        workspace = state.workspace

        system_prefix = None
        if workspace is not None:
            system_prefix = self._get_cached_system_prefix(
                workspace, tools or [], deferred_tool_count
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
    ) -> str:
        """Build system prefix with a cache keyed by workspace, tools, and deferred count."""
        key = self._system_prefix_cache_key(workspace, tools, deferred_tool_count)
        if self._cached_key == key and self._cached_system_prefix is not None:
            return self._cached_system_prefix
        rendered = self._build_system_prefix(workspace, tools, deferred_tool_count)
        self._cached_key = key
        self._cached_system_prefix = rendered
        return rendered

    def _system_prefix_cache_key(
        self,
        workspace,
        tools: Sequence[ToolSpec],
        deferred_tool_count: int = 0,
    ) -> str:
        """Deterministic cache key that invalidates on file/tool changes."""
        global_path = Path(workspace.global_system_prompt_path)
        soul_path = Path(workspace.soul_path)
        db_path = resolve_db_path()
        global_mtime = global_path.stat().st_mtime_ns if global_path.exists() else 0
        soul_mtime = soul_path.stat().st_mtime_ns if soul_path.exists() else 0
        db_mtime = db_path.stat().st_mtime_ns if db_path.exists() else 0
        tools_shape = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in sorted(tools, key=lambda t: t.name)
        ]
        payload = {
            "agent_id": workspace.agent_id,
            "global_system_prompt_path": str(global_path),
            "global_mtime_ns": global_mtime,
            "soul_path": str(soul_path),
            "soul_mtime_ns": soul_mtime,
            "db_path": str(db_path),
            "db_mtime_ns": db_mtime,
            "tools": tools_shape,
            "deferred_tool_count": deferred_tool_count,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_system_prefix(
        self,
        workspace,
        tools: Sequence[ToolSpec],
        deferred_tool_count: int = 0,
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

        tools_block_lines: list[str] = []
        if tools:
            tools_block_lines.append("AVAILABLE TOOLS:")
            for tool in sorted(tools, key=lambda t: t.name):
                tools_block_lines.append(f"- {tool.name}: {tool.description}")
        tools_block = "\n".join(tools_block_lines)

        user_profile_text = self._build_user_profile_context()

        parts = []
        if global_text:
            parts.append(global_text.strip())
        if soul_text:
            parts.append("YOUR IDENTITY:\n" + soul_text.strip())
        if tools_block:
            parts.append(tools_block)
        if user_profile_text:
            parts.append(user_profile_text)
        if deferred_tool_count > 0:
            parts.append(
                f"## search_tools — {deferred_tool_count} additional tool(s) available on demand\n\n"
                "Not all tools are loaded at startup. Before attempting any action, check whether the "
                "required tool is in your current tool list. If it is not, you MUST call `search_tools` "
                "first — NEVER hallucinate that an action was taken or use a wrong tool as a substitute.\n\n"
                "Rules:\n"
                "- You MUST call `search_tools(query=\"...\")` before using any tool that is not already in your tool list.\n"
                "- Do NOT use a read/list tool to perform a write/send action (e.g. do NOT use `mcp_read_emails` to send email).\n"
                "- Do NOT tell the user an action was completed if you did not successfully call the correct tool.\n"
                "- After `search_tools` returns, the matched tools are immediately active — call them in the next step.\n\n"
                "Examples of when to call search_tools first:\n"
                "- User wants to send an email → search_tools('send email') → then call mcp_send_email\n"
                "- User wants to create a calendar event → search_tools('create calendar event') → then call mcp_calendar_create_event\n"
                "- User wants to write an Obsidian note → search_tools('obsidian note') → then call mcp_obsidian_create_note\n"
                "- User wants to create a Notion page → search_tools('notion page') → then call mcp_notion_create_page"
            )

        return "\n\n".join(parts).strip()

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

