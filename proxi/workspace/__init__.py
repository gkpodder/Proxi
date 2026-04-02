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
            default = Path(__file__).parent / "default_system_prompt.md"
            path.write_text(default.read_text(encoding="utf-8"), encoding="utf-8")
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
        working_dir: str | None = None,
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
                and existing.get("working_dir") == working_dir
            ):
                return
            raise WorkspaceError(
                f"Agent {agent_id!r} already registered in gateway.yml with different settings"
            )

        entry: dict[str, Any] = {"soul": rel_soul, "default_session": default_session}
        if working_dir is not None:
            entry["working_dir"] = working_dir
        agents[agent_id] = entry
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
        working_dir: str | None = None,
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
            self.register_agent_in_gateway(
                agent_id, default_session=default_session, working_dir=working_dir
            )

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

    def branch_agent(
        self,
        parent_agent_id: str,
        source_history_path: str | Path,
        *,
        default_session: str = "main",
        working_dir: str | None = None,
    ) -> AgentInfo:
        """Create a new agent that is a clone of parent_agent_id.

        Copies Soul.md and config.yaml from the parent. Copies source_history_path
        into the new agent's first session so the LLM prompt cache is warm.

        The new agent_id is {base}-2 (or -3, etc.), stripping any existing -N suffix
        so repeated branching stays flat: proxi → proxi-2 → proxi-3.
        """
        import re
        import shutil

        self._validate_agent_id(parent_agent_id)
        self.ensure_base_dirs()
        parent_dir = self.agents_dir / parent_agent_id
        if not parent_dir.exists():
            raise WorkspaceError(f"Parent agent {parent_agent_id!r} not found")

        base = re.sub(r"-\d+$", "", parent_agent_id)
        new_agent_id: str | None = None
        for n in range(2, 1000):
            candidate = f"{base}-{n}"
            if not (self.agents_dir / candidate).exists():
                new_agent_id = candidate
                break
        if new_agent_id is None:
            raise WorkspaceError("No available branch name (tried up to -999)")

        new_dir = self.agents_dir / new_agent_id
        new_dir.mkdir(parents=True, exist_ok=False)

        for fname in ("Soul.md", "config.yaml"):
            src = parent_dir / fname
            if src.exists():
                (new_dir / fname).write_bytes(src.read_bytes())

        session_dir = new_dir / "sessions" / default_session
        session_dir.mkdir(parents=True, exist_ok=True)
        src_hist = Path(source_history_path)
        dst_hist = session_dir / "history.jsonl"
        if src_hist.exists() and src_hist.stat().st_size > 0:
            shutil.copy2(src_hist, dst_hist)
        else:
            dst_hist.write_text("", encoding="utf-8")

        self.register_agent_in_gateway(
            new_agent_id, default_session=default_session, working_dir=working_dir
        )
        return AgentInfo(agent_id=new_agent_id, path=new_dir)

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

    def create_named_session(
        self,
        agent: AgentInfo,
        session_name: str,
        *,
        source_history_path: str | Path | None = None,
    ) -> SessionInfo:
        """Create a new session with a specific name without disturbing other sessions.

        Unlike create_single_session, this does NOT remove existing sessions.
        If source_history_path is provided, its content is copied into the new
        session's history.jsonl (for prompt-cache-friendly inheritance).
        """
        import shutil

        self.ensure_base_dirs()
        session_dir = agent.path / "sessions" / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        history_path = session_dir / "history.jsonl"
        if source_history_path is not None:
            src = Path(source_history_path)
            if src.exists() and src.stat().st_size > 0:
                shutil.copy2(src, history_path)
            else:
                history_path.write_text("", encoding="utf-8")
        elif not history_path.exists():
            history_path.write_text("", encoding="utf-8")
        return SessionInfo(
            agent=agent,
            session_id=session_name,
            session_dir=session_dir,
            history_path=history_path,
            plan_path=session_dir / "plan.md",
            todos_path=session_dir / "todos.md",
        )

    def delete_session(self, agent_id: str, session_name: str) -> None:
        """Delete a session directory from disk. No-op if it does not exist."""
        import shutil

        session_dir = self.agents_dir / agent_id / "sessions" / session_name
        if session_dir.exists():
            shutil.rmtree(session_dir)

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
