"""Gateway configuration parsed from ``gateway.yml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class GatewayConfigError(RuntimeError):
    """Raised when ``gateway.yml`` is missing or malformed."""


@dataclass
class AgentConfig:
    agent_id: str
    soul_path: Path
    default_session: str = "main"
    working_dir: Path | None = None


@dataclass
class SourceConfig:
    source_id: str
    source_type: str  # "channel" | "http" | "cron" | "heartbeat" | "webhook"
    target_agent: str
    # If False and target_agent is set, the TUI launcher exports PROXI_SESSION_ID (auto-connect).
    pick_agent_at_startup: bool = True
    target_session: str = ""
    priority: int = 0
    paused: bool = False
    # cron
    schedule: str = ""
    prompt: str = ""
    # heartbeat
    interval: int = 0
    deadline_s: int = 0
    # webhook
    secret_env: str = ""
    prompt_template: str = ""

    # extra fields from YAML that don't map to known attrs
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewayConfig:
    agents: dict[str, AgentConfig]
    sources: dict[str, SourceConfig]
    workspace_root: Path

    @classmethod
    def load(cls, workspace_root: Path) -> GatewayConfig:
        path = workspace_root / "gateway.yml"
        if not path.exists():
            raise GatewayConfigError(f"gateway.yml not found at {path}")

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise GatewayConfigError("gateway.yml must be a YAML mapping")

        agents: dict[str, AgentConfig] = {}
        for aid, cfg in (raw.get("agents") or {}).items():
            raw_wd = cfg.get("working_dir")
            agents[aid] = AgentConfig(
                agent_id=aid,
                soul_path=(workspace_root / cfg["soul"]).resolve(),
                default_session=cfg.get("default_session", "main"),
                working_dir=Path(raw_wd).expanduser().resolve() if raw_wd else None,
            )

        sources: dict[str, SourceConfig] = {}
        for sid, cfg in (raw.get("sources") or {}).items():
            known_keys = {
                "type", "target_agent", "target_session", "priority",
                "paused",
                "pick_agent_at_startup",
                "schedule", "prompt", "interval", "deadline_s",
                "secret_env", "prompt_template",
            }
            extras = {k: v for k, v in cfg.items() if k not in known_keys}
            sources[sid] = SourceConfig(
                source_id=sid,
                source_type=cfg.get("type", ""),
                target_agent=cfg.get("target_agent", ""),
                pick_agent_at_startup=cfg.get("pick_agent_at_startup", True),
                target_session=cfg.get("target_session", ""),
                priority=cfg.get("priority", 0),
                paused=bool(cfg.get("paused", False)),
                schedule=cfg.get("schedule", ""),
                prompt=cfg.get("prompt", ""),
                interval=cfg.get("interval", 0),
                deadline_s=cfg.get("deadline_s", 0),
                secret_env=cfg.get("secret_env", ""),
                prompt_template=cfg.get("prompt_template", ""),
                extras=extras,
            )

        return cls(agents=agents, sources=sources, workspace_root=workspace_root)

    def session_history_path(self, agent_id: str, session_name: str) -> Path:
        """Return the path to a session's history.jsonl file."""
        return (
            self.workspace_root
            / "agents"
            / agent_id
            / "sessions"
            / session_name
            / "history.jsonl"
        )

    def session_dir(self, agent_id: str, session_name: str) -> Path:
        return self.workspace_root / "agents" / agent_id / "sessions" / session_name
