"""Tests for proxi.gateway — config, events, routing, lanes, channels, and heartbeat integration."""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from proxi.core.state import AgentState, AgentStatus, Message, WorkspaceConfig
from proxi.gateway.channels.base import ChannelAdapter
from proxi.gateway.channels.discord import DiscordAdapter
from proxi.gateway.channels.heartbeat import HeartbeatManager
from proxi.gateway.channels.http import (
    HttpFormBridge,
    HttpNoopReplyChannel,
    HttpReplyChannel,
    HttpSseReplyChannel,
    build_http_event,
)
from proxi.gateway.channels.telegram import TelegramAdapter
from proxi.gateway.channels.webhook import render_prompt_template
from proxi.gateway.channels.whatsapp import WhatsAppAdapter
from proxi.gateway.config import AgentConfig, GatewayConfig, GatewayConfigError, SourceConfig
from proxi.gateway.events import GatewayEvent, ReplyChannel
from proxi.gateway.lanes.budget import BudgetExceeded, LaneBudget
from proxi.gateway.lanes.manager import LaneManager
from proxi.gateway.router import EventRouter, RoutingError
from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    tmp_path: Path,
    *,
    agents: dict[str, dict[str, str]] | None = None,
    sources: dict[str, dict[str, Any]] | None = None,
) -> GatewayConfig:
    """Build a GatewayConfig from dicts, creating soul files on disk."""
    if agents is None:
        agents = {
            "work": {"soul": "agents/work/soul.md", "default_session": "main"},
        }
    if sources is None:
        sources = {
            "telegram": {"type": "channel", "target_agent": "work"},
        }

    for aid, acfg in agents.items():
        soul = tmp_path / acfg["soul"]
        soul.parent.mkdir(parents=True, exist_ok=True)
        soul.write_text(f"Soul for {aid}", encoding="utf-8")

    (tmp_path / "global").mkdir(parents=True, exist_ok=True)
    (tmp_path / "global" / "system_prompt.md").write_text("system", encoding="utf-8")

    gateway_yml = {"agents": agents, "sources": sources}
    (tmp_path / "gateway.yml").write_text(yaml.dump(gateway_yml), encoding="utf-8")
    return GatewayConfig.load(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════
# GatewayEvent
# ═══════════════════════════════════════════════════════════════════════════

class TestGatewayEvent:
    def test_defaults(self) -> None:
        event = GatewayEvent(source_id="tg", source_type="telegram", payload={"text": "hi"})
        assert event.event_id  # uuid auto-generated
        assert event.session_id == ""
        assert event.priority == 0
        assert event.timestamp is not None

    def test_priority_override(self) -> None:
        event = GatewayEvent(source_id="hb", source_type="heartbeat", payload={}, priority=-2)
        assert event.priority == -2

    def test_session_id_stamp(self) -> None:
        event = GatewayEvent(source_id="x", source_type="http", payload={})
        event.session_id = "work/main"
        assert event.session_id == "work/main"


# ═══════════════════════════════════════════════════════════════════════════
# GatewayConfig
# ═══════════════════════════════════════════════════════════════════════════

class TestGatewayConfig:
    def test_load_basic(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        assert "work" in config.agents
        assert "telegram" in config.sources
        assert config.agents["work"].default_session == "main"

    def test_soul_path_resolved(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        assert config.agents["work"].soul_path.is_absolute()
        assert config.agents["work"].soul_path.exists()

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(GatewayConfigError, match="gateway.yml not found"):
            GatewayConfig.load(tmp_path)

    def test_session_history_path(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        p = config.session_history_path("work", "main")
        assert p == tmp_path / "agents" / "work" / "sessions" / "main" / "history.jsonl"

    def test_session_dir(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        d = config.session_dir("work", "side")
        assert d == tmp_path / "agents" / "work" / "sessions" / "side"

    def test_multiple_agents_and_sources(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path,
            agents={
                "work": {"soul": "agents/work/soul.md", "default_session": "main"},
                "research": {"soul": "agents/research/soul.md", "default_session": "main"},
            },
            sources={
                "telegram": {"type": "channel", "target_agent": "work"},
                "cron_daily": {
                    "type": "cron",
                    "schedule": "0 8 * * *",
                    "prompt": "do stuff",
                    "target_agent": "research",
                },
            },
        )
        assert len(config.agents) == 2
        assert len(config.sources) == 2
        assert config.sources["cron_daily"].schedule == "0 8 * * *"

    def test_source_defaults(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        src = config.sources["telegram"]
        assert src.priority == 0
        assert src.target_session == ""
        assert src.schedule == ""
        assert src.pick_agent_at_startup is True

    def test_tui_pick_agent_at_startup_from_yaml(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path,
            sources={
                "tui": {
                    "type": "http",
                    "target_agent": "work",
                    "pick_agent_at_startup": False,
                },
            },
        )
        assert config.sources["tui"].pick_agent_at_startup is False

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        (tmp_path / "gateway.yml").write_text("not_a_mapping", encoding="utf-8")
        with pytest.raises(GatewayConfigError, match="must be a YAML mapping"):
            GatewayConfig.load(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════
# EventRouter
# ═══════════════════════════════════════════════════════════════════════════

class TestEventRouter:
    def _router(self, tmp_path: Path, **kwargs: Any) -> EventRouter:
        config = _make_config(tmp_path, **kwargs)
        return EventRouter(config)

    def test_resolve_happy_path(self, tmp_path: Path) -> None:
        router = self._router(tmp_path)
        event = GatewayEvent(source_id="telegram", source_type="telegram", payload={})
        assert router.resolve(event) == "work/main"

    def test_resolve_explicit_session_override(self, tmp_path: Path) -> None:
        router = self._router(
            tmp_path,
            sources={
                "telegram": {
                    "type": "channel",
                    "target_agent": "work",
                    "target_session": "side",
                },
            },
        )
        event = GatewayEvent(source_id="telegram", source_type="telegram", payload={})
        assert router.resolve(event) == "work/side"

    def test_resolve_unknown_source_raises(self, tmp_path: Path) -> None:
        router = self._router(tmp_path)
        event = GatewayEvent(source_id="unknown", source_type="http", payload={})
        with pytest.raises(RoutingError, match="No source config"):
            router.resolve(event)

    def test_resolve_unknown_agent_raises(self, tmp_path: Path) -> None:
        router = self._router(
            tmp_path,
            sources={"bad": {"type": "channel", "target_agent": "ghost"}},
        )
        event = GatewayEvent(source_id="bad", source_type="http", payload={})
        with pytest.raises(RoutingError, match="unknown agent"):
            router.resolve(event)

    def test_resolve_default(self, tmp_path: Path) -> None:
        router = self._router(tmp_path)
        assert router.resolve_default() == "work/main"

    def test_resolve_default_no_agents_raises(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.agents.clear()
        router = EventRouter(config)
        with pytest.raises(RoutingError, match="No agents configured"):
            router.resolve_default()


# ═══════════════════════════════════════════════════════════════════════════
# LaneBudget
# ═══════════════════════════════════════════════════════════════════════════

class TestLaneBudget:
    def test_fresh_budget_passes(self) -> None:
        budget = LaneBudget(max_turns=5, token_budget=1000)
        budget.check()

    def test_turn_limit_exceeded(self) -> None:
        budget = LaneBudget(max_turns=2)
        budget.record_turn(context_tokens=10)
        # 2nd record_turn brings turns_used to 2 == max_turns → raises
        with pytest.raises(BudgetExceeded, match="turn limit"):
            budget.record_turn(context_tokens=10)

    def test_token_budget_exceeded(self) -> None:
        budget = LaneBudget(token_budget=100)
        with pytest.raises(BudgetExceeded, match="token budget"):
            budget.record_turn(context_tokens=200)

    def test_reset_clears_counters(self) -> None:
        budget = LaneBudget(max_turns=5, token_budget=1000)
        budget.record_turn(context_tokens=500)
        assert budget.turns_used == 1
        assert budget.tokens_used == 500
        budget.reset()
        assert budget.turns_used == 0
        assert budget.tokens_used == 0

    def test_under_limit_does_not_raise(self) -> None:
        budget = LaneBudget(max_turns=10, token_budget=5000)
        for _ in range(5):
            budget.record_turn(context_tokens=100)
        assert budget.turns_used == 5
        assert budget.tokens_used == 100  # SET semantics: reflects latest context size


# ═══════════════════════════════════════════════════════════════════════════
# AgentState.load
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentStateLoad:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert AgentState.load(tmp_path / "nope.jsonl") is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        assert AgentState.load(p) is None

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "blanks.jsonl"
        p.write_text("\n\n\n", encoding="utf-8")
        assert AgentState.load(p) is None

    def test_valid_messages(self, tmp_path: Path) -> None:
        p = tmp_path / "history.jsonl"
        lines = [
            json.dumps({"role": "user", "content": "hello"}),
            json.dumps({"role": "assistant", "content": "hi there"}),
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        state = AgentState.load(p)
        assert state is not None
        assert state.status == AgentStatus.IDLE
        assert len(state.history) == 2
        assert state.history[0].role == "user"
        assert state.history[0].content == "hello"
        assert state.history[1].role == "assistant"

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "mixed.jsonl"
        p.write_text(
            "not json at all\n"
            + json.dumps({"role": "user", "content": "ok"}) + "\n"
            + "{bad json\n",
            encoding="utf-8",
        )
        state = AgentState.load(p)
        assert state is not None
        assert len(state.history) == 1

    def test_non_message_objects_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "interaction.jsonl"
        p.write_text(
            json.dumps({"type": "interaction", "goal": "test"}) + "\n"
            + json.dumps({"role": "user", "content": "yes"}) + "\n",
            encoding="utf-8",
        )
        state = AgentState.load(p)
        assert state is not None
        assert len(state.history) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Channel adapters — parse()
# ═══════════════════════════════════════════════════════════════════════════

class TestTelegramAdapter:
    async def test_parse_message(self) -> None:
        raw = {
            "message": {
                "chat": {"id": 123456},
                "text": "Hello from Telegram",
            }
        }
        event = await TelegramAdapter().parse(raw)
        assert event is not None
        assert event.source_id == "telegram"
        assert event.source_type == "telegram"
        assert event.payload["text"] == "Hello from Telegram"
        assert event.reply_channel is not None
        assert event.reply_channel.destination == "123456"

    async def test_parse_no_message_returns_none(self) -> None:
        assert await TelegramAdapter().parse({"update_id": 1}) is None

    async def test_parse_no_text_returns_none(self) -> None:
        raw = {"message": {"chat": {"id": 1}, "sticker": {}}}
        assert await TelegramAdapter().parse(raw) is None


class TestWhatsAppAdapter:
    async def test_parse_text_message(self) -> None:
        raw = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "15551234567",
                            "text": {"body": "Hi from WhatsApp"},
                        }]
                    }
                }]
            }]
        }
        event = await WhatsAppAdapter().parse(raw)
        assert event is not None
        assert event.payload["text"] == "Hi from WhatsApp"
        assert event.reply_channel.destination == "15551234567"

    async def test_parse_empty_entry_returns_none(self) -> None:
        assert await WhatsAppAdapter().parse({"entry": []}) is None

    async def test_parse_no_messages_returns_none(self) -> None:
        raw = {"entry": [{"changes": [{"value": {"statuses": []}}]}]}
        assert await WhatsAppAdapter().parse(raw) is None


class TestDiscordAdapter:
    async def test_parse_message(self) -> None:
        raw = {"content": "Hello Discord", "channel_id": "999"}
        event = await DiscordAdapter().parse(raw)
        assert event is not None
        assert event.payload["text"] == "Hello Discord"
        assert event.reply_channel.destination == "999"

    async def test_parse_no_content_returns_none(self) -> None:
        assert await DiscordAdapter().parse({"type": 1}) is None


# ═══════════════════════════════════════════════════════════════════════════
# Webhook template rendering
# ═══════════════════════════════════════════════════════════════════════════

class TestRenderPromptTemplate:
    def test_simple_substitution(self) -> None:
        result = render_prompt_template("Hello {{name}}", {"name": "world"})
        assert result == "Hello world"

    def test_nested_key(self) -> None:
        data = {"repository": {"name": "myrepo"}, "action": "push"}
        result = render_prompt_template(
            "New: {{action}} on {{repository.name}}", data
        )
        assert result == "New: push on myrepo"

    def test_missing_key_preserved(self) -> None:
        result = render_prompt_template("{{missing}}", {})
        assert result == "{{missing}}"

    def test_no_placeholders(self) -> None:
        assert render_prompt_template("plain text", {}) == "plain text"


# ═══════════════════════════════════════════════════════════════════════════
# HTTP reply channel
# ═══════════════════════════════════════════════════════════════════════════

class TestHttpReplyChannel:
    async def test_send_and_collect(self) -> None:
        reply = HttpReplyChannel(source_type="http", destination="test")
        await reply.send("hello back")
        text = await reply.collect(timeout=1.0)
        assert text == "hello back"

    async def test_collect_timeout(self) -> None:
        reply = HttpReplyChannel(source_type="http", destination="test")
        with pytest.raises(asyncio.TimeoutError):
            await reply.collect(timeout=0.05)

    def test_build_http_event(self) -> None:
        event, reply = build_http_event("test message", session_id="work/main")
        assert event.source_type == "http"
        assert event.payload["text"] == "test message"
        assert event.session_id == "work/main"
        assert reply is event.reply_channel


# ═══════════════════════════════════════════════════════════════════════════
# LaneManager
# ═══════════════════════════════════════════════════════════════════════════

class TestLaneManager:
    def _make_manager(self, tmp_path: Path) -> LaneManager:
        config = _make_config(tmp_path)
        stub_factory = lambda wc: None  # noqa: E731
        return LaneManager(config, create_loop=stub_factory)

    async def test_get_or_create_creates_lane(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        lane = mgr._get_or_create("work/main")
        assert lane.session_id == "work/main"
        assert lane.soul_path.exists()
        session_dir = tmp_path / "agents" / "work" / "sessions" / "main"
        assert session_dir.exists()
        await mgr.shutdown()

    async def test_get_or_create_reuses_lane(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        first = mgr._get_or_create("work/main")
        second = mgr._get_or_create("work/main")
        assert first is second
        await mgr.shutdown()

    async def test_list_lanes(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert mgr.list_lanes() == []
        mgr._get_or_create("work/main")
        lanes = mgr.list_lanes()
        assert len(lanes) == 1
        assert lanes[0]["session_id"] == "work/main"
        await mgr.shutdown()

    def test_get_lane_returns_none_for_unknown(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        assert mgr.get_lane("nope/nope") is None

    async def test_route_asserts_session_id(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        event = GatewayEvent(source_id="tg", source_type="telegram", payload={})
        with pytest.raises(AssertionError):
            await mgr.route(event)

    async def test_route_enqueues_event(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        event = GatewayEvent(
            source_id="telegram",
            source_type="telegram",
            payload={"text": "hi"},
            session_id="work/main",
        )
        await mgr.route(event)
        lane = mgr.get_lane("work/main")
        assert lane is not None
        # The drain task may or may not have pulled the event yet;
        # verify the lane was created and the event was accepted.
        assert lane.session_id == "work/main"
        await mgr.shutdown()

    async def test_shutdown_clears_lanes(self, tmp_path: Path) -> None:
        mgr = self._make_manager(tmp_path)
        mgr._get_or_create("work/main")
        assert len(mgr.list_lanes()) == 1
        await mgr.shutdown()
        assert len(mgr.list_lanes()) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Full pipeline: event → router → lane
# ═══════════════════════════════════════════════════════════════════════════

class TestEventPipeline:
    async def test_event_routes_to_correct_lane(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path,
            agents={
                "work": {"soul": "agents/work/soul.md", "default_session": "main"},
                "research": {"soul": "agents/research/soul.md", "default_session": "main"},
            },
            sources={
                "telegram": {"type": "channel", "target_agent": "work"},
                "cron_weekly": {
                    "type": "cron",
                    "target_agent": "research",
                    "schedule": "0 9 * * MON",
                    "prompt": "go",
                },
            },
        )
        router = EventRouter(config)
        mgr = LaneManager(config, create_loop=lambda wc: None)

        tg_event = GatewayEvent(source_id="telegram", source_type="telegram", payload={"text": "hey"})
        tg_event.session_id = router.resolve(tg_event)
        assert tg_event.session_id == "work/main"
        await mgr.route(tg_event)

        cron_event = GatewayEvent(source_id="cron_weekly", source_type="cron", payload={"text": "go"})
        cron_event.session_id = router.resolve(cron_event)
        assert cron_event.session_id == "research/main"
        await mgr.route(cron_event)

        assert mgr.get_lane("work/main") is not None
        assert mgr.get_lane("research/main") is not None

        await mgr.shutdown()

    async def test_priority_ordering_in_queue(self, tmp_path: Path) -> None:
        """Events with higher priority dequeue before lower-priority ones."""
        config = _make_config(tmp_path)

        # Build a lane directly (no drain task) so we can inspect queue order.
        from proxi.gateway.lanes.lane import AgentLane
        from proxi.gateway.lanes.budget import LaneBudget

        lane = AgentLane(
            session_id="work/main",
            soul_path=config.agents["work"].soul_path,
            history_path=config.session_history_path("work", "main"),
            workspace_config=WorkspaceConfig(
                workspace_root=str(tmp_path),
                agent_id="work",
                session_id="main",
                global_system_prompt_path="",
                soul_path="",
                history_path="",
                plan_path="",
                todos_path="",
            ),
            budget=LaneBudget(),
        )
        # Don't call start() — we just want to test queue ordering.

        for priority, label in [(0, "user"), (-1, "webhook"), (-2, "heartbeat")]:
            await lane.enqueue(GatewayEvent(
                source_id="x",
                source_type="telegram",
                payload={"text": label},
                session_id="work/main",
                priority=priority,
            ))

        assert lane.queue_depth == 3

        items = []
        while not lane.queue.empty():
            neg_pri, seq, ev = lane.queue.get_nowait()
            items.append((ev.payload["text"], ev.priority))

        assert items[0] == ("user", 0)
        assert items[1] == ("webhook", -1)
        assert items[2] == ("heartbeat", -2)


# ═══════════════════════════════════════════════════════════════════════════
# HeartbeatManager — integration test with gateway.yml
# ═══════════════════════════════════════════════════════════════════════════

class TestHeartbeatIntegration:
    """Integration test that writes a real ``gateway.yml`` to a temp
    ``.proxi/`` workspace, starts the ``HeartbeatManager``, and verifies
    that events arrive in the correct lane on schedule.
    """

    @staticmethod
    def _write_workspace(root: Path) -> None:
        """Create a minimal .proxi workspace with a heartbeat source."""
        (root / "global").mkdir(parents=True, exist_ok=True)
        (root / "global" / "system_prompt.md").write_text("You are Proxi.", encoding="utf-8")

        agent_dir = root / "agents" / "work"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "soul.md").write_text(
            "Name: Work\nPersona: Helpful\nMission: Test", encoding="utf-8"
        )

        gateway_yml = textwrap.dedent("""\
            agents:
              work:
                soul: agents/work/soul.md
                default_session: main

            sources:
              heartbeat_fast:
                type: heartbeat
                interval: 1
                prompt: "heartbeat ping"
                target_agent: work
                priority: -2
        """)
        (root / "gateway.yml").write_text(gateway_yml, encoding="utf-8")

    async def test_heartbeat_fires_events_into_lane(self, tmp_path: Path) -> None:
        """Verify a heartbeat source actually enqueues events on its interval.

        We spy on ``LaneManager.route`` to count routed events because
        the lane's drain task may consume events from the queue before
        we can inspect ``queue_depth``.
        """
        workspace = tmp_path / ".proxi"
        self._write_workspace(workspace)

        config = GatewayConfig.load(workspace)

        # Validate config was parsed correctly from gateway.yml
        assert "heartbeat_fast" in config.sources
        hb_source = config.sources["heartbeat_fast"]
        assert hb_source.source_type == "heartbeat"
        assert hb_source.interval == 1
        assert hb_source.prompt == "heartbeat ping"
        assert hb_source.priority == -2

        router = EventRouter(config)
        lane_manager = LaneManager(config, create_loop=lambda wc: None)

        routed_events: list[GatewayEvent] = []
        original_route = lane_manager.route

        async def spy_route(event: GatewayEvent) -> None:
            routed_events.append(event)
            await original_route(event)

        lane_manager.route = spy_route  # type: ignore[assignment]
        heartbeat_mgr = HeartbeatManager(config, lane_manager, router)

        await heartbeat_mgr.start()

        # The heartbeat sleeps *first*, then fires. After ~2.5s we
        # expect at least 2 events (fires at t≈1s and t≈2s).
        await asyncio.sleep(2.5)

        await heartbeat_mgr.stop()

        assert len(routed_events) >= 2, (
            f"Expected >= 2 heartbeat events, got {len(routed_events)}"
        )

        # Verify event content
        for ev in routed_events:
            assert ev.source_id == "heartbeat_fast"
            assert ev.source_type == "heartbeat"
            assert ev.payload["text"] == "heartbeat ping"
            assert ev.priority == -2
            assert ev.session_id == "work/main"

        # Verify lane was created
        lane = lane_manager.get_lane("work/main")
        assert lane is not None

        await lane_manager.shutdown()

    async def test_heartbeat_skips_invalid_interval(self, tmp_path: Path) -> None:
        """A heartbeat with interval <= 0 should not start a background task."""
        config = GatewayConfig(
            agents={"work": AgentConfig(agent_id="work", soul_path=tmp_path / "soul.md")},
            sources={
                "bad_hb": SourceConfig(
                    source_id="bad_hb",
                    source_type="heartbeat",
                    target_agent="work",
                    interval=0,
                    prompt="nope",
                ),
            },
            workspace_root=tmp_path,
        )
        router = EventRouter(config)
        lane_manager = LaneManager(config, create_loop=lambda wc: None)
        heartbeat_mgr = HeartbeatManager(config, lane_manager, router)

        await heartbeat_mgr.start()
        assert len(heartbeat_mgr._tasks) == 0
        await heartbeat_mgr.stop()
        await lane_manager.shutdown()

    async def test_heartbeat_stop_cancels_tasks(self, tmp_path: Path) -> None:
        """Calling stop() cleanly cancels all running heartbeat tasks."""
        workspace = tmp_path / ".proxi"
        self._write_workspace(workspace)

        config = GatewayConfig.load(workspace)
        router = EventRouter(config)
        lane_manager = LaneManager(config, create_loop=lambda wc: None)
        heartbeat_mgr = HeartbeatManager(config, lane_manager, router)

        await heartbeat_mgr.start()
        assert len(heartbeat_mgr._tasks) == 1
        assert not heartbeat_mgr._tasks[0].done()

        await heartbeat_mgr.stop()
        assert len(heartbeat_mgr._tasks) == 0

        await lane_manager.shutdown()

    async def test_heartbeat_routes_to_correct_agent(self, tmp_path: Path) -> None:
        """When two agents exist, heartbeat events land in the right lane."""
        root = tmp_path / ".proxi"
        (root / "global").mkdir(parents=True, exist_ok=True)
        (root / "global" / "system_prompt.md").write_text("system", encoding="utf-8")

        for agent_id in ("work", "research"):
            d = root / "agents" / agent_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "soul.md").write_text(f"Soul: {agent_id}", encoding="utf-8")

        cfg = {
            "agents": {
                "work": {"soul": "agents/work/soul.md", "default_session": "main"},
                "research": {"soul": "agents/research/soul.md", "default_session": "main"},
            },
            "sources": {
                "hb_work": {
                    "type": "heartbeat",
                    "interval": 1,
                    "prompt": "work ping",
                    "target_agent": "work",
                },
                "hb_research": {
                    "type": "heartbeat",
                    "interval": 1,
                    "prompt": "research ping",
                    "target_agent": "research",
                },
            },
        }
        (root / "gateway.yml").write_text(yaml.dump(cfg), encoding="utf-8")

        config = GatewayConfig.load(root)
        router = EventRouter(config)
        lane_manager = LaneManager(config, create_loop=lambda wc: None)

        # Spy on route to track which events reach which session
        routed: dict[str, list[GatewayEvent]] = {}
        original_route = lane_manager.route

        async def spy_route(event: GatewayEvent) -> None:
            routed.setdefault(event.session_id, []).append(event)
            await original_route(event)

        lane_manager.route = spy_route  # type: ignore[assignment]
        heartbeat_mgr = HeartbeatManager(config, lane_manager, router)

        await heartbeat_mgr.start()
        await asyncio.sleep(1.5)
        await heartbeat_mgr.stop()

        assert "work/main" in routed, "Expected work heartbeat events"
        assert "research/main" in routed, "Expected research heartbeat events"

        assert all(e.payload["text"] == "work ping" for e in routed["work/main"])
        assert all(e.payload["text"] == "research ping" for e in routed["research/main"])

        await lane_manager.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# ReplyChannel subclass behaviour
# ═══════════════════════════════════════════════════════════════════════════

class TestReplyChannel:
    async def test_base_send_raises(self) -> None:
        ch = ReplyChannel(source_type="http", destination="x")
        with pytest.raises(NotImplementedError):
            await ch.send("hello")

    async def test_custom_reply_channel(self) -> None:
        collected: list[str] = []

        class TestReply(ReplyChannel):
            source_type: str = "http"  # type: ignore[assignment]

            async def send(self, text: str) -> None:
                collected.append(text)

        reply = TestReply(destination="test")
        await reply.send("one")
        await reply.send("two")
        assert collected == ["one", "two"]


# ═══════════════════════════════════════════════════════════════════════════
# HttpSseReplyChannel
# ═══════════════════════════════════════════════════════════════════════════

class TestHttpSseReplyChannel:
    async def test_send_and_stream(self) -> None:
        sse = HttpSseReplyChannel(destination="sse:work/main")
        await sse.send("hello")
        await sse.send("world")
        await sse.close()

        chunks = []
        async for item in sse.stream():
            chunks.append(item)
        assert chunks == [
            {"type": "text_stream", "content": "hello"},
            {"type": "text_stream", "content": "world"},
        ]

    async def test_send_event(self) -> None:
        sse = HttpSseReplyChannel(destination="sse:test")
        await sse.send_event({"type": "status_update", "label": "Running...", "status": "running"})
        await sse.close()

        items = []
        async for item in sse.stream():
            items.append(item)
        assert len(items) == 1
        assert items[0]["type"] == "status_update"

    async def test_close_terminates_stream(self) -> None:
        sse = HttpSseReplyChannel(destination="sse:test")
        await sse.close()
        items = [item async for item in sse.stream()]
        assert items == []


class TestHttpNoopReplyChannel:
    async def test_send_does_nothing(self) -> None:
        ch = HttpNoopReplyChannel(destination="noop")
        await ch.send("ignored")  # should not raise


# ═══════════════════════════════════════════════════════════════════════════
# HttpFormBridge
# ═══════════════════════════════════════════════════════════════════════════

class TestHttpFormBridge:
    async def test_inject_answer_resolves_future(self) -> None:
        sse = HttpSseReplyChannel(destination="sse:form")
        bridge = HttpFormBridge(sse)

        class FakeFormRequest:
            goal = "test"
            title = "Test Form"
            questions = []
            allow_skip = False

        async def inject_after_delay():
            await asyncio.sleep(0.05)
            await bridge.inject_answer({"tool_call_id": "tc_1", "answers": {"a": 1}, "skipped": False})

        task = asyncio.create_task(inject_after_delay())
        result = await bridge.request_form("tc_1", FakeFormRequest())
        await task
        assert result["answers"] == {"a": 1}

        # Verify the form event was sent to SSE
        await sse.close()
        events = [item async for item in sse.stream()]
        assert any(e["type"] == "user_input_required" for e in events)


# ═══════════════════════════════════════════════════════════════════════════
# Lane SSE attachment
# ═══════════════════════════════════════════════════════════════════════════

class TestLaneSseAttachment:
    def test_attach_and_detach(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        from proxi.gateway.lanes.lane import AgentLane

        lane = AgentLane(
            session_id="work/main",
            soul_path=config.agents["work"].soul_path,
            history_path=config.session_history_path("work", "main"),
            workspace_config=WorkspaceConfig(
                workspace_root=str(tmp_path),
                agent_id="work",
                session_id="main",
                global_system_prompt_path="",
                soul_path="",
                history_path="",
                plan_path="",
                todos_path="",
            ),
            budget=LaneBudget(),
        )
        sse = HttpSseReplyChannel(destination="sse:work/main")
        bridge = HttpFormBridge(sse)
        lane.attach_sse(sse, bridge)
        assert lane._sse_channel is sse
        assert lane._form_bridge is bridge

        lane.detach_sse()
        assert lane._sse_channel is None
        assert lane._form_bridge is None

    def test_stale_detach_does_not_clear_new_attachment(self, tmp_path: Path) -> None:
        """Older SSE stream teardown must not detach the latest stream."""
        config = _make_config(tmp_path)
        from proxi.gateway.lanes.lane import AgentLane

        lane = AgentLane(
            session_id="work/main",
            soul_path=config.agents["work"].soul_path,
            history_path=config.session_history_path("work", "main"),
            workspace_config=WorkspaceConfig(
                workspace_root=str(tmp_path),
                agent_id="work",
                session_id="main",
                global_system_prompt_path="",
                soul_path="",
                history_path="",
                plan_path="",
                todos_path="",
            ),
            budget=LaneBudget(),
        )

        sse_old = HttpSseReplyChannel(destination="sse:work/main:old")
        bridge_old = HttpFormBridge(sse_old)
        lane.attach_sse(sse_old, bridge_old)

        sse_new = HttpSseReplyChannel(destination="sse:work/main:new")
        bridge_new = HttpFormBridge(sse_new)
        lane.attach_sse(sse_new, bridge_new)

        # Simulate old stream's finally block running late.
        lane.detach_sse(sse_old)
        assert lane._sse_channel is sse_new
        assert lane._form_bridge is bridge_new

        lane.detach_sse(sse_new)
        assert lane._sse_channel is None
        assert lane._form_bridge is None


# ═══════════════════════════════════════════════════════════════════════════
# MCP tool registry sync (live lanes after gateway refresh)
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentLaneSyncMcpTools:
    def test_replaces_mcp_tools_keeps_non_mcp(self, tmp_path: Path) -> None:
        from proxi.gateway.lanes.lane import AgentLane

        class StubTool(BaseTool):
            async def execute(self, arguments: dict[str, Any]) -> ToolResult:
                return ToolResult(success=True, output="")

        config = _make_config(tmp_path)
        reg = ToolRegistry()
        old_mcp = StubTool("mcp_weather_get_current", "", {})
        reg.register(old_mcp)
        reg.register(StubTool("manage_plan", "", {}))

        class FakeLoop:
            tool_registry = reg

        lane = AgentLane(
            session_id="work/main",
            soul_path=config.agents["work"].soul_path,
            history_path=config.session_history_path("work", "main"),
            workspace_config=WorkspaceConfig(
                workspace_root=str(tmp_path),
                agent_id="work",
                session_id="main",
                global_system_prompt_path="",
                soul_path="",
                history_path="",
                plan_path="",
                todos_path="",
            ),
            budget=LaneBudget(),
        )
        lane._loop = FakeLoop()  # type: ignore[assignment]

        fresh_mcp = StubTool("mcp_weather_get_current", "", {})
        lane.sync_mcp_tools([fresh_mcp])

        assert reg.get("manage_plan") is not None
        assert reg.get("mcp_weather_get_current") is fresh_mcp
        assert reg.get("mcp_weather_get_current") is not old_mcp


# ═══════════════════════════════════════════════════════════════════════════
# HttpFormBridge — chat replies while a collaborative form is pending
# ═══════════════════════════════════════════════════════════════════════════


class TestClearSessionHistory:
    @pytest.mark.asyncio
    async def test_truncates_disk_when_no_lane(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        hist = config.session_history_path("work", "main")
        hist.parent.mkdir(parents=True, exist_ok=True)
        hist.write_text('{"role":"user","content":"x"}\n', encoding="utf-8")
        lm = LaneManager(config, create_loop=lambda wc_agent: None)
        await lm.clear_session_history("work/main")
        assert hist.read_text() == ""

    def test_invalid_session_id_raises(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        lm = LaneManager(config, create_loop=lambda wc_agent: None)
        with pytest.raises(ValueError):
            lm.session_history_path("bad-session")


class TestHttpFormBridgeConsumeChat:
    @pytest.mark.asyncio
    async def test_consume_chat_resolves_single_pending_form(self) -> None:
        from proxi.gateway.channels.http import HttpFormBridge, HttpSseReplyChannel
        from proxi.interaction.models import FormRequest, Question

        ch = HttpSseReplyChannel(destination="sse:test")
        fb = HttpFormBridge(ch)
        fr = FormRequest(
            goal="format",
            questions=[
                Question(
                    id="fmt",
                    type="choice",
                    question="Which?",
                    options=["Full message body", "Summary only"],
                    why="need user preference",
                )
            ],
        )

        async def waiter() -> dict[str, Any]:
            return await fb.request_form("call_x", fr)

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        assert fb.consume_chat_as_form_reply("full") is True
        out = await task
        assert out["answers"]["fmt"] == "Full message body"

    def test_consume_chat_no_ops_without_pending(self) -> None:
        from proxi.gateway.channels.http import HttpFormBridge, HttpSseReplyChannel

        fb = HttpFormBridge(HttpSseReplyChannel(destination="sse:x"))
        assert fb.consume_chat_as_form_reply("hello") is False


# ═══════════════════════════════════════════════════════════════════════════
# SourceConfig deadline_s
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceConfigDeadline:
    def test_deadline_s_parsed(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path,
            sources={
                "hb": {
                    "type": "heartbeat",
                    "target_agent": "work",
                    "interval": 60,
                    "prompt": "check",
                    "deadline_s": 120,
                },
            },
        )
        assert config.sources["hb"].deadline_s == 120

    def test_deadline_s_default_zero(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        assert config.sources["telegram"].deadline_s == 0
