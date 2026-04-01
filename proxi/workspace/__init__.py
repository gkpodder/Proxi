"""Workspace management for global/agent/session directories.

This module provides a filesystem-backed workspace layout:

~/.proxi/
├── global/
│   └── system_prompt.md
└── agents/
    └── <agent_id>/
        ├── Soul.md
        ├── config.yaml        # (reserved for future use)
        └── sessions/
            └── <session_id>/
                ├── history.jsonl
                ├── plan.md    # (optional, created via tools)
                └── todos.md   # (optional, created via tools)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from proxi.core.state import WorkspaceConfig


class WorkspaceError(RuntimeError):
    """Raised when workspace operations fail."""


@dataclass
class AgentInfo:
    """Metadata about an agent workspace."""

    agent_id: str
    path: Path


@dataclass
class SessionInfo:
    """Metadata about a single (ephemeral) session."""

    agent: AgentInfo
    session_id: str
    session_dir: Path
    history_path: Path
    plan_path: Path
    todos_path: Path

    @property
    def workspace_config(self) -> WorkspaceConfig:
        """Convert to WorkspaceConfig for attachment to AgentState."""
        root = self.agent.path.parent.parent
        global_dir = root / "global"
        return WorkspaceConfig(
            workspace_root=str(root),
            agent_id=self.agent.agent_id,
            session_id=self.session_id,
            global_system_prompt_path=str(global_dir / "system_prompt.md"),
            soul_path=str(self.agent.path / "Soul.md"),
            history_path=str(self.history_path),
            plan_path=str(self.plan_path),
            todos_path=str(self.todos_path),
        )


class WorkspaceManager:
    """Filesystem-backed manager for global, agent, and session workspaces."""

    def __init__(self, root: Path | None = None) -> None:
        from os import getenv

        home_override = getenv("PROXI_HOME")
        if root is None:
            if home_override:
                root = Path(home_override).expanduser()
            else:
                root = Path.home() / ".proxi"

        self.root = root.expanduser().resolve()
        self.global_dir = self.root / "global"
        self.agents_dir = self.root / "agents"

    # --- Global workspace -------------------------------------------------

    def ensure_base_dirs(self) -> None:
        """Ensure the global/agents directories exist."""
        self.global_dir.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    def ensure_global_system_prompt(self) -> Path:
        """Ensure global/system_prompt.md exists with workspace instructions."""
        self.ensure_base_dirs()
        path = self.global_dir / "system_prompt.md"
        if not path.exists():
            # Initial content from project system_pompt.md
            content = (
                "You are Proxi — a personal AI agent that lives on the user's computer and operates it through natural language. You replace menus, mice, terminals, and application UIs with a single conversation. Your purpose is to make computing genuinely accessible without sacrificing the depth that power users depend on.\n\n"
                "Your personality, tone, and values are defined in your soul. When your soul conflicts with these instructions, your soul wins — except on safety, which is non-negotiable.\n\n"
                "---\n\n"
                "## Who You're Talking To\n\n"
                "Your users range from people who've never opened a terminal to engineers who want zero hand-holding. Read the conversation and adapt — vocabulary, depth, pacing — to the person in front of you.\n\n"
                "For users showing confusion, distress, or repeated misunderstanding: slow down, simplify, and confirm understanding before acting. Never make someone feel inadequate for not knowing something.\n\n"
                "---\n\n"
                "## The Agent Loop\n\n"
                "Each turn, choose exactly one action:\n\n"
                "**RESPOND** — Deliver the complete final answer to the user. **RESPOND ends the turn immediately — no tool calls will run after it.** Only use RESPOND when you have finished all work and are ready to give the full result. Never use RESPOND to announce what you are about to do — phrases like 'I'll now run X' or 'I'll report back' must not appear in a RESPOND. If you still have work to do, use TOOL_CALL instead (you can narrate your reasoning in the text before the tool call).\n\n"
                "**TOOL_CALL** — Execute a tool. You may stream reasoning text before the tool call so the user can follow your progress.\n\n"
                "**SUB_AGENT_CALL** — Delegate to a specialised sub-agent. Synthesise results before returning them — the user talks to you, not the sub-agent.\n\n"
                "**REQUEST_USER_INPUT** — Call `ask_user_question` when genuinely blocked by missing information.\n\n"
                "---\n\n"
                "## Scoping Ambiguous Requests\n\n"
                "When a request is ambiguous and a wrong assumption would waste significant effort or cause real harm — scope before acting using `ask_user_question`.\n\n"
                "**Use a form when:**\n"
                "- Two or more interpretations lead to meaningfully different outcomes\n"
                "- You need a specific value you cannot safely infer\n"
                "- The action is irreversible and your assumption might be wrong\n\n"
                "**Skip the form when:**\n"
                "- You can make a reasonable assumption, state it, and the cost of being wrong is low\n"
                "- One conversational question in RESPOND is faster and less disruptive\n"
                "- The answer is already in the conversation\n\n"
                "**When building a form:**\n"
                "- `goal` — one sentence: what you're trying to determine\n"
                "- `hint` — plain-language explanation shown to the user per question\n"
                "- `why` — internal reasoning for the Reflector, not shown to the user\n"
                "- Prefer `yesno` / `choice` over `text` — constrained options are faster and more accessible\n"
                "- Ask only what you can't infer. Every unnecessary question costs the user attention.\n"
                "- Don't add an \"Other\" option to `options` arrays — the TUI adds it automatically\n\n"
                "---\n\n"
                "## Tool Discipline\n\n"
                "Before any tool call, tell the user what you're doing in one plain sentence. After, report the result before moving on. Never silently proceed.\n\n"
                "**Require explicit confirmation before:** deleting files, making purchases, uninstalling software, modifying system or security settings. Use a `yesno` form question.\n\n"
                "On failure: explain what went wrong in plain language — no raw stack traces. Describe your recovery plan and ask the user if you can't recover autonomously.\n\n"
                "Prefer the least invasive path. Read before writing. Check before deleting.\n\n"
                "---\n\n"
                "## Safety\n\n"
                "Some users rely on Proxi as their primary interface to their computer — treat that seriously.\n\n"
                "If a request would harm the user, their data, or others — decline, and be honest about why. Don't dress a refusal up as a technical limitation.\n\n"
                "Never store credentials or sensitive data in the plan, todos, or history beyond the immediate tool call that needs them.\n\n"
                "If a user seems to be in genuine distress beyond the computing task — pause. Respond as a person first. The task can wait.\n\n"
                "---\n\n"
                "## How to Communicate\n\n"
                "Be direct and warm — not formal, not a yes-man. Push back when something is a bad idea. Suggest a better approach when you see one. Be honest when you don't know something. A good friend who happens to be an expert doesn't just agree — they tell you the truth.\n\n"
                "Don't pad responses. No \"Great question!\", no unnecessary preamble. Start with the answer or the action.\n\n"
                "Match the user's pace. Short messages get short replies. Depth gets depth.\n\n"
                "For multi-step tasks: give a brief plan upfront, report at meaningful checkpoints, confirm clearly when done.\n\n"
                "Plain language is the default. Use technical terms only when the user has shown they're comfortable with them.\n\n"
                "---\n\n"
                "## What You're Not\n\n"
                "You're not a command executor that blindly runs whatever it's told. You're an agent with judgment and a real relationship with the person you serve — which means you sometimes push back, ask questions, or suggest a better path, always in service of what's actually good for them.\n\n"
                "The measure of a good turn: did the user's situation genuinely improve?\n\n"
                "---\n\n"
                "## Coding Agent\n\n"
                "When coding tools are available (`read_file`, `write_file`, `edit_file`, `execute_code`, `grep`, `glob`, `apply_patch`), follow these rules:\n\n"
                "To get the current date and time, use `execute_code` with `date` (Unix) or `Get-Date` (PowerShell).\n\n"
                "**File operations**\n"
                "- Always `read_file` before `edit_file` — never edit blind.\n"
                "- Use `write_file` for new files, `edit_file` for changes to existing files.\n"
                "- Relative paths automatically resolve inside the working directory — use them.\n"
                "- Never read or write outside the working directory unless the user explicitly instructs it.\n\n"
                "**Git discipline — high caution**\n"
                "- Never `git commit`, `git push`, create or delete branches, or `git reset` without explicit user approval for that specific action.\n"
                "- Never use `--force`, `--no-verify`, or `--force-with-lease` unless the user asks.\n"
                "- Prefer creating a new commit over amending an existing one.\n"
                "- Treat uncommitted changes as the user's in-progress work — do not discard them.\n\n"
                "**Code execution safety**\n"
                "- Run tests after making changes and report failures before moving on.\n"
                "- Do not install packages globally (`pip install`, `npm install -g`, `brew install`) without confirming with the user.\n"
                "- Do not run commands that modify system state or security settings without a `yesno` confirmation.\n\n"
                "**Task discipline**\n"
                "- For tasks touching more than three files or requiring more than five tool calls, outline the plan first and confirm before executing.\n"
                "- After completing a coding task, summarise what changed and whether tests passed — don't just stop.\n"
                "- If a command fails, diagnose the error before retrying. Don't retry the same failing command blindly."
            )
            path.write_text(content, encoding="utf-8")
        return path

    # --- Agents -----------------------------------------------------------

    def list_agents(self) -> list[AgentInfo]:
        """Discover existing agents under agents/."""
        if not self.agents_dir.exists():
            return []
        agents: list[AgentInfo] = []
        for child in sorted(self.agents_dir.iterdir()):
            if child.is_dir():
                agents.append(AgentInfo(agent_id=child.name, path=child))
        return agents

    def register_agent_in_gateway(
        self,
        agent_id: str,
        *,
        default_session: str = "main",
    ) -> None:
        """Add or idempotently confirm this agent in ``gateway.yml``.

        Creates a minimal ``gateway.yml`` if missing (``agents`` + ``sources``).
        Paths under ``agents:`` are relative to the workspace root.
        """
        rel_soul = f"agents/{agent_id}/Soul.md"
        soul_abs = (self.root / rel_soul).resolve()
        if not soul_abs.exists():
            raise WorkspaceError(
                f"Cannot register {agent_id!r}: missing {rel_soul} under {self.root}"
            )

        path = self.root / "gateway.yml"
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            raw = {"agents": {}, "sources": {}}
        if not isinstance(raw, dict):
            raise WorkspaceError("gateway.yml must be a YAML mapping")

        agents: dict[str, Any] = raw.get("agents") or {}
        if not isinstance(agents, dict):
            agents = {}
        existing = agents.get(agent_id)
        if isinstance(existing, dict):
            if (
                existing.get("soul") == rel_soul
                and existing.get("default_session", "main") == default_session
            ):
                return
            raise WorkspaceError(
                f"Agent {agent_id!r} already registered in gateway.yml with different settings"
            )

        agents[agent_id] = {"soul": rel_soul, "default_session": default_session}
        raw["agents"] = agents
        if "sources" not in raw:
            raw["sources"] = {}

        path.write_text(
            yaml.safe_dump(
                raw,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def create_agent(
        self,
        name: str,
        persona: str,
        agent_id: str | None = None,
        *,
        sync_gateway: bool = True,
        default_session: str = "main",
    ) -> AgentInfo:
        """Create a new agent directory and Soul.md."""
        self.ensure_base_dirs()
        if agent_id is None:
            agent_id = self._slugify(name) or "agent"

        agent_dir = self.agents_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        soul_path = agent_dir / "Soul.md"
        if not soul_path.exists():
            soul_content = f"Name: {name}\nPersona: {persona}\n"
            soul_path.write_text(soul_content, encoding="utf-8")

        config_path = agent_dir / "config.yaml"
        if not config_path.exists():
            config_content = "tool_sets:\n  coding: live  # live | deferred | disabled\n"
            config_path.write_text(config_content, encoding="utf-8")

        if sync_gateway:
            self.register_agent_in_gateway(agent_id, default_session=default_session)

        return AgentInfo(agent_id=agent_id, path=agent_dir)

    def delete_agent(self, agent_id: str) -> None:
        """Remove an agent from ``gateway.yml`` and delete ``agents/<agent_id>/``.

        Sources that pointed at this agent are rewired to another remaining agent.
        Cannot delete the last registered agent (create another first).
        """
        import shutil

        self._validate_agent_id(agent_id)
        self.ensure_base_dirs()

        path = self.root / "gateway.yml"
        if not path.exists():
            raise WorkspaceError("gateway.yml not found")

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise WorkspaceError("gateway.yml must be a YAML mapping")

        agents: dict[str, Any] = raw.get("agents") or {}
        if not isinstance(agents, dict):
            agents = {}
        if agent_id not in agents:
            raise WorkspaceError(f"Agent {agent_id!r} is not registered in gateway.yml")
        if len(agents) <= 1:
            raise WorkspaceError(
                "Cannot delete the last agent; create another agent first"
            )

        remaining = [k for k in agents if k != agent_id]
        replacement = remaining[0]

        del agents[agent_id]
        raw["agents"] = agents

        sources = raw.get("sources") or {}
        if isinstance(sources, dict):
            for cfg in sources.values():
                if isinstance(cfg, dict) and cfg.get("target_agent") == agent_id:
                    cfg["target_agent"] = replacement

        path.write_text(
            yaml.safe_dump(
                raw,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        agent_dir = self.agents_dir / agent_id
        if agent_dir.exists():
            shutil.rmtree(agent_dir)

    # --- Sessions ---------------------------------------------------------

    def create_single_session(self, agent: AgentInfo) -> SessionInfo:
        """Create a fresh single-use session for an agent.

        Any existing sessions/<*> directories are removed first to enforce
        a single ephemeral session per agent.
        """
        import shutil
        from datetime import datetime, timezone

        self.ensure_base_dirs()
        sessions_root = agent.path / "sessions"
        if sessions_root.exists():
            shutil.rmtree(sessions_root)
        sessions_root.mkdir(parents=True, exist_ok=True)

        session_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        session_dir = sessions_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        history_path = session_dir / "history.jsonl"
        plan_path = session_dir / "plan.md"
        todos_path = session_dir / "todos.md"

        # Initialize empty history file
        history_path.write_text("", encoding="utf-8")

        return SessionInfo(
            agent=agent,
            session_id=session_id,
            session_dir=session_dir,
            history_path=history_path,
            plan_path=plan_path,
            todos_path=todos_path,
        )

    def read_agent_config(self, agent_id: str) -> dict[str, Any]:
        """Read and return the parsed config.yaml for an agent.

        Returns an empty dict if the file is missing or unparseable.
        """
        config_path = self.agents_dir / agent_id / "config.yaml"
        if not config_path.exists():
            return {}
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    # --- Workspace context helpers ---------------------------------------

    def build_workspace_config(self, session: SessionInfo) -> WorkspaceConfig:
        """Helper to build WorkspaceConfig from a SessionInfo."""
        # This simply proxies SessionInfo.workspace_config for convenience.
        return session.workspace_config

    # --- Internal helpers -------------------------------------------------

    @staticmethod
    def _validate_agent_id(agent_id: str) -> None:
        if not agent_id or agent_id != agent_id.strip():
            raise WorkspaceError("Invalid agent id")
        if agent_id in (".", "..") or "/" in agent_id or "\\" in agent_id:
            raise WorkspaceError("Invalid agent id")

    @staticmethod
    def _slugify(value: str) -> str:
        """Simple filesystem-safe slug from a name."""
        value = value.strip().lower()
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
        return "".join(ch if ch in allowed else "-" for ch in value)
