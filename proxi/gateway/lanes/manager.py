"""LaneManager — owns the dict of session_id → AgentLane."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Sequence

from proxi.core.state import WorkspaceConfig
from proxi.gateway.config import GatewayConfig
from proxi.gateway.events import GatewayEvent
from proxi.gateway.lanes.budget import LaneBudget
from proxi.gateway.lanes.lane import AgentLane
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class LaneManager:
    def __init__(
        self,
        config: GatewayConfig,
        create_loop: Callable[[WorkspaceConfig], Any],
    ) -> None:
        self._config = config
        self._lanes: dict[str, AgentLane] = {}
        self._create_loop = create_loop

    async def route(self, event: GatewayEvent) -> None:
        assert event.session_id, "session_id must be stamped by EventRouter before routing"
        lane = self._get_or_create(event.session_id)
        await lane.enqueue(event)

    async def resume(self, session_id: str, form_answer: dict[str, Any]) -> None:
        lane = self._lanes.get(session_id)
        if lane:
            await lane.resume(form_answer)

    def list_lanes(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": sid,
                "queue_depth": lane.queue_depth,
                "running": lane.is_running,
            }
            for sid, lane in self._lanes.items()
        ]

    def get_lane(self, session_id: str) -> AgentLane | None:
        return self._lanes.get(session_id)

    def session_history_path(self, session_id: str) -> Path:
        """``session_id`` is ``{agent_id}/{session_name}``."""
        parts = session_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"invalid session_id: {session_id!r}")
        agent_id, session_name = parts
        return self._config.session_history_path(agent_id, session_name)

    async def clear_session_history(self, session_id: str) -> None:
        """Truncate disk history for this session and reset any live lane."""
        hist = self.session_history_path(session_id)
        hist.parent.mkdir(parents=True, exist_ok=True)
        lane = self._lanes.get(session_id)
        if lane is not None:
            await lane.clear_session_history()
        else:
            hist.write_text("", encoding="utf-8")

    async def shutdown(self) -> None:
        for lane in self._lanes.values():
            await lane.stop()
        self._lanes.clear()

    def sync_mcp_tools_to_loops(self, mcp_tools: Sequence[Any]) -> None:
        """After gateway MCP refresh, update tool registries on running loops."""
        for lane in self._lanes.values():
            lane.sync_mcp_tools(list(mcp_tools))

    def _get_or_create(self, session_id: str) -> AgentLane:
        if session_id in self._lanes:
            return self._lanes[session_id]

        agent_id, session_name = session_id.split("/", 1)
        agent = self._config.agents[agent_id]

        session_dir = self._config.session_dir(agent_id, session_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        history_path = self._config.session_history_path(agent_id, session_name)

        workspace_root = str(self._config.workspace_root)
        global_prompt = str(self._config.workspace_root / "global" / "system_prompt.md")

        workspace_config = WorkspaceConfig(
            workspace_root=workspace_root,
            agent_id=agent_id,
            session_id=session_name,
            global_system_prompt_path=global_prompt,
            soul_path=str(agent.soul_path),
            history_path=str(history_path),
            plan_path=str(session_dir / "plan.md"),
            todos_path=str(session_dir / "todos.md"),
        )

        lane = AgentLane(
            session_id=session_id,
            soul_path=agent.soul_path,
            history_path=history_path,
            workspace_config=workspace_config,
            budget=LaneBudget(),
            _create_loop=self._create_loop,
        )
        asyncio.create_task(lane.start())
        self._lanes[session_id] = lane
        logger.info("lane_created", session_id=session_id)
        return lane
