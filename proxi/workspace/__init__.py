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
from typing import Iterable

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
            # Initial content describes workspace capabilities.
            content = (
                "You are Proxi, a helpful AI assistant.\n\n"
                "You have a session-specific workspace on disk. For complex tasks, use the\n"
                "`update_plan` tool to maintain a strategy and `manage_todos` to track\n"
                "progress. These files are optional; only create them if they help you\n"
                "stay organized. Your current workspace state will be provided to you at\n"
                "the start of each turn if it exists.\n"
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

    def create_agent(
        self,
        name: str,
        persona: str,
        mission: str,
        agent_id: str | None = None,
    ) -> AgentInfo:
        """Create a new agent directory and Soul.md."""
        self.ensure_base_dirs()
        if agent_id is None:
            agent_id = self._slugify(name) or "agent"

        agent_dir = self.agents_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        soul_path = agent_dir / "Soul.md"
        if not soul_path.exists():
            soul_content = (
                f"Name: {name}\n"
                f"Persona: {persona}\n"
                f"Mission: {mission}\n"
            )
            soul_path.write_text(soul_content, encoding="utf-8")

        # Placeholder for future config.yaml support
        (agent_dir / "config.yaml").touch(exist_ok=True)

        return AgentInfo(agent_id=agent_id, path=agent_dir)

    # --- Sessions ---------------------------------------------------------

    def create_single_session(self, agent: AgentInfo) -> SessionInfo:
        """Create a fresh single-use session for an agent.

        Any existing sessions/<*> directories are removed first to enforce
        a single ephemeral session per agent.
        """
        import shutil
        from datetime import datetime

        self.ensure_base_dirs()
        sessions_root = agent.path / "sessions"
        if sessions_root.exists():
            shutil.rmtree(sessions_root)
        sessions_root.mkdir(parents=True, exist_ok=True)

        session_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
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

    # --- Workspace context helpers ---------------------------------------

    def build_workspace_config(self, session: SessionInfo) -> WorkspaceConfig:
        """Helper to build WorkspaceConfig from a SessionInfo."""
        # This simply proxies SessionInfo.workspace_config for convenience.
        return session.workspace_config

    # --- Internal helpers -------------------------------------------------

    @staticmethod
    def _slugify(value: str) -> str:
        """Simple filesystem-safe slug from a name."""
        value = value.strip().lower()
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
        return "".join(ch if ch in allowed else "-" for ch in value)
