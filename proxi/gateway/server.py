"""Gateway FastAPI application — lifespan, endpoints, and intake pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from proxi.cli.main import (
    auto_load_mcp_servers,
    create_llm_client,
    setup_sub_agents,
    setup_tools,
)
from proxi.core.compactor import ContextCompactor
from proxi.core.loop import AgentLoop
from proxi.core.state import WorkspaceConfig
from proxi.gateway.channels.cron import CronRegistry, _parse_cron
from proxi.gateway.channels.discord import DiscordAdapter
from proxi.gateway.channels.heartbeat import HeartbeatManager
from proxi.gateway.channels.http import (
    HttpFormBridge,
    HttpNoopReplyChannel,
    HttpSseReplyChannel,
    build_http_event,
)
from proxi.gateway.channels.telegram import TelegramAdapter
from proxi.gateway.channels.webhook import build_webhook_event
from proxi.gateway.channels.whatsapp import WhatsAppAdapter
from proxi.gateway.config import GatewayConfig
from proxi.gateway.events import GatewayEvent
from proxi.gateway.lanes.manager import LaneManager
from proxi.gateway.middleware.auth import verify_bearer_token
from proxi.gateway.middleware.hmac import (
    verify_discord_signature,
    verify_telegram_signature,
    verify_webhook_hmac,
    verify_whatsapp_signature,
)
from proxi.gateway.router import EventRouter
from proxi.interaction.tool import get_ask_user_question_spec
from proxi.llm.model_registry import (
    DEFAULT_MODELS,
    get_context_window,
    get_model_limits_by_provider,
    get_supported_models_by_provider,
)
from proxi.observability.logging import get_logger, init_log_manager
from proxi.security.key_store import get_user_profile
from proxi.tools.coding import register_coding_tools
from proxi.tools.workspace_tools import ManagePlanTool, ManageTodosTool, ReadSoulTool
from proxi.workspace import AgentInfo, WorkspaceError, WorkspaceManager

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (populated during lifespan)
# ---------------------------------------------------------------------------
config: GatewayConfig
router: EventRouter
lane_manager: LaneManager | None = None
heartbeat_mgr: HeartbeatManager
scheduler = AsyncIOScheduler()
memory_manager: Any | None = None  # MemoryManager, initialised in lifespan

SUPPORTED_LLM_MODELS: dict[str, list[str]] = get_supported_models_by_provider()
LLM_MODEL_LIMITS: dict[str, list[dict[str, int | str]]
                       ] = get_model_limits_by_provider()
DEFAULT_LLM_MODELS: dict[str, str] = dict(DEFAULT_MODELS)
llm_provider: str = "openai"
llm_model: str = DEFAULT_LLM_MODELS["openai"]

# MCP-type integration adapters loaded once at startup; injected into each lane.
_mcp_adapters: list[Any] = []
_integration_tools: list[Any] = []           # live (always-loaded) integration tools
# deferred integration tools (loaded via search_tools)
_integration_deferred_tools: list[Any] = []
_last_integration_signature: str | None = None
_integration_refresh_lock = asyncio.Lock()

# CLI tools loaded once at startup; share the same lane injection as integration tools.
_cli_tools: list[Any] = []           # live CLI tools
_cli_deferred_tools: list[Any] = []  # deferred CLI tools (found via call_tool)

# Global working directory fallback (env var / POST /v1/working-dir with no agent).
_working_dir: Path = Path(os.environ.get("PROXI_WORKING_DIR", ".")).resolve()

# Per-agent runtime working dirs. Seeded from gateway.yml at startup; overridden
# by POST /v1/working-dir when the TUI sends an agent_id.
_agent_working_dirs: dict[str, Path] = {}


def _workspace_root() -> Path:
    """Resolve the .proxi workspace root."""
    env = os.environ.get("PROXI_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".proxi"


def _purge_all_plans(workspace_root: Path) -> None:
    """Delete all files inside every agents/{agent_id}/plans/ directory.

    Plans are ephemeral: they should not survive a gateway restart or crash.
    """
    import glob as _glob
    for plan_file in _glob.glob(str(workspace_root / "agents" / "*" / "plans" / "*")):
        try:
            Path(plan_file).unlink(missing_ok=True)
        except Exception:
            pass


def _reload_gateway_config() -> None:
    """Reload ``gateway.yml`` and sync in-memory router + lane manager."""
    global config, router
    root = _workspace_root()
    config = GatewayConfig.load(root)
    router = EventRouter(config)
    if lane_manager is not None:
        lane_manager.update_config(config)
    # Seed per-agent working dirs from yaml for agents not yet overridden at runtime.
    for aid, agent_cfg in config.agents.items():
        if agent_cfg.working_dir and aid not in _agent_working_dirs:
            _agent_working_dirs[aid] = agent_cfg.working_dir


def _gateway_config_path() -> Path:
    return _workspace_root() / "gateway.yml"


def _load_gateway_raw_config() -> dict[str, Any]:
    path = _gateway_config_path()
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"gateway.yml not found at {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=500, detail="gateway.yml must be a YAML mapping")

    if not isinstance(raw.get("agents"), dict):
        raw["agents"] = {}
    if not isinstance(raw.get("sources"), dict):
        raw["sources"] = {}
    return raw


def _write_gateway_raw_config(raw: dict[str, Any]) -> None:
    path = _gateway_config_path()
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _reload_cron_registry() -> None:
    # Scheduler in this gateway process only hosts cron jobs.
    for job in scheduler.get_jobs():
        scheduler.remove_job(job.id)

    if lane_manager is None:
        return

    CronRegistry(config, lane_manager, router).load_all(scheduler)


def _persist_and_reload_gateway_config(raw: dict[str, Any]) -> None:
    _write_gateway_raw_config(raw)
    _reload_gateway_config()
    _reload_cron_registry()


def _normalize_provider(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized not in SUPPORTED_LLM_MODELS:
        raise ValueError(
            f"Unsupported provider: {provider}. Expected one of: {', '.join(sorted(SUPPORTED_LLM_MODELS))}",
        )
    return normalized


def _resolve_model(provider: str, model: str | None) -> str:
    requested = (model or "").strip()
    if not requested:
        return DEFAULT_LLM_MODELS[provider]

    allowed = SUPPORTED_LLM_MODELS.get(provider, [])
    # Empty allowed list means models are user-defined (e.g. vllm) — skip validation.
    if allowed and requested not in allowed:
        raise ValueError(f"Unsupported model for {provider}: {requested}")
    return requested


async def _refresh_integration_tools() -> None:
    """Reload MCP and CLI integration tools when config or enable flags change."""
    global _mcp_adapters, _integration_tools, _integration_deferred_tools, _last_integration_signature

    async with _integration_refresh_lock:
        from proxi.cli.main import load_integrations_config
        from proxi.security.key_store import get_enabled_integrations

        sig_payload = {
            "enabled": sorted(get_enabled_integrations()),
            "config": load_integrations_config(),
        }
        sig = hashlib.sha256(
            json.dumps(sig_payload, sort_keys=True,
                       separators=(",", ":")).encode()
        ).hexdigest()
        if sig == _last_integration_signature:
            return
        _last_integration_signature = sig

        no_mcp = os.environ.get("PROXI_NO_MCP", "").lower() in ("1", "true", "yes")
        if not no_mcp:
            for adapter in _mcp_adapters:
                try:
                    await asyncio.wait_for(adapter.close(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("mcp_close_timeout")
                except Exception as exc:
                    logger.warning("mcp_close_error", error=str(exc))
            _mcp_adapters.clear()
            _integration_tools.clear()
            _integration_deferred_tools.clear()

            try:
                from proxi.tools.registry import ToolRegistry as _TR

                tmp_registry = _TR()
                _mcp_adapters[:] = await asyncio.wait_for(
                    auto_load_mcp_servers(tmp_registry), timeout=30.0
                )
                _integration_tools[:] = list(tmp_registry._tools.values())
                _integration_deferred_tools[:] = list(
                    tmp_registry._deferred_tools.values())
                logger.info(
                    "integrations_refreshed",
                    adapters=len(_mcp_adapters),
                    tools=len(_integration_tools),
                    deferred=len(_integration_deferred_tools),
                )
            except Exception as exc:
                logger.warning("integration_refresh_error", error=str(exc))
        else:
            for adapter in _mcp_adapters:
                try:
                    await asyncio.wait_for(adapter.close(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("mcp_close_timeout")
                except Exception as exc:
                    logger.warning("mcp_close_error", error=str(exc))
            _mcp_adapters.clear()
            _integration_tools.clear()
            _integration_deferred_tools.clear()

        _refresh_cli_tools()

        # Existing lanes keep the same AgentLoop + ToolRegistry; refresh replaces
        # global tool objects — push the new tools into every active loop so
        # toggles take effect without restarting the gateway.
        if lane_manager is not None:
            lane_manager.sync_mcp_tools_to_loops(
                _integration_tools, _integration_deferred_tools)
            lane_manager.sync_cli_tools_to_loops(
                _cli_tools, _cli_deferred_tools)


def _refresh_cli_tools() -> None:
    """Load CLI tools from config + key store into global lists."""
    global _cli_tools, _cli_deferred_tools
    from proxi.cli.main import build_cli_tool_lists

    live, deferred = build_cli_tool_lists()
    _cli_tools.clear()
    _cli_deferred_tools.clear()
    _cli_tools.extend(live)
    _cli_deferred_tools.extend(deferred)
    logger.info(
        "cli_tools_loaded",
        live=len(_cli_tools),
        deferred=len(_cli_deferred_tools),
    )


def _create_agent_loop(workspace_config: WorkspaceConfig) -> AgentLoop:
    """Factory called by LaneManager to create an AgentLoop per session.

    Each lane gets its own tool registry so workspace-scoped tools
    (plan, todos, soul) resolve to the correct session paths.
    MCP tools loaded at gateway startup are shared across all lanes.
    """
    llm_client = create_llm_client(provider=llm_provider, model=llm_model)

    working_dir = _agent_working_dirs.get(
        workspace_config.agent_id, _working_dir)

    tool_registry = setup_tools(working_directory=working_dir)
    tool_registry.register_raw_spec(get_ask_user_question_spec())
    tool_registry.register(ManagePlanTool(workspace_config))
    tool_registry.register(ManageTodosTool(workspace_config))
    tool_registry.register(ReadSoulTool(workspace_config))

    # Register coding tools based on per-agent config
    workspace_manager = WorkspaceManager(root=_workspace_root())
    agent_config = workspace_manager.read_agent_config(
        workspace_config.agent_id)
    coding_tier = agent_config.get("tool_sets", {}).get("coding", "live")
    register_coding_tools(
        tool_registry, working_dir=working_dir, tier=str(coding_tier))

    workspace_config.curr_working_dir = str(working_dir)

    for mcp_tool in _integration_tools:
        tool_registry.register(mcp_tool)
    for mcp_tool in _integration_deferred_tools:
        tool_registry.register_deferred(mcp_tool)
    for cli_tool in _cli_tools:
        tool_registry.register(cli_tool)
    for cli_tool in _cli_deferred_tools:
        tool_registry.register_deferred(cli_tool)
    if tool_registry.has_deferred_tools():
        from proxi.tools.call_tool_tool import CallToolTool
        tool_registry.register(CallToolTool(tool_registry))

    # Register memory tools if memory is enabled for this agent
    if memory_manager is not None:
        _agent_mem_enabled = config.agents.get(workspace_config.agent_id)
        if _agent_mem_enabled is None or _agent_mem_enabled.memory_enabled:
            from proxi.tools.memory_tools import SearchMemoryTool, SaveSkillTool, UpdateUserModelTool
            tool_registry.register(SearchMemoryTool(memory_manager))
            tool_registry.register(SaveSkillTool(memory_manager))
            tool_registry.register(UpdateUserModelTool(memory_manager))

    no_sub_agents = os.environ.get("PROXI_NO_SUB_AGENTS", "").lower() in (
        "1", "true", "yes",
    )
    sub_agent_manager = None if no_sub_agents else setup_sub_agents(llm_client)

    max_turns = int(os.environ.get("PROXI_MAX_TURNS", "500"))
    compactor = ContextCompactor(
        llm_client=llm_client,
        context_window=get_context_window(llm_model),
    )
    return AgentLoop(
        llm_client=llm_client,
        tool_registry=tool_registry,
        sub_agent_manager=sub_agent_manager,
        max_turns=max_turns,
        enable_reflection=True,
        workspace=workspace_config,
        compactor=compactor,
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    global config, router, lane_manager, heartbeat_mgr
    global _mcp_adapters, _integration_tools
    global llm_provider, llm_model
    global memory_manager

    workspace_root = _workspace_root()
    WorkspaceManager(root=workspace_root).ensure_global_system_prompt()

    # Initialize memory system
    from proxi.memory.manager import MemoryManager as _MemoryManager
    memory_manager = _MemoryManager(
        memory_dir=workspace_root / "memory",
        gateway_config_path=workspace_root / "gateway.yml",
    )
    memory_manager.init()

    config = GatewayConfig.load(workspace_root)
    router = EventRouter(config)

    # Seed per-agent working dirs from gateway.yml.
    for _aid, _agent_cfg in config.agents.items():
        if _agent_cfg.working_dir:
            _agent_working_dirs[_aid] = _agent_cfg.working_dir

    env_provider_raw = os.environ.get("PROXI_PROVIDER", "openai")
    try:
        env_provider = _normalize_provider(env_provider_raw)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    env_model = os.environ.get("PROXI_MODEL", "") or os.environ.get(
        f"PROXI_{env_provider.upper()}_MODEL", ""
    )
    llm_provider = env_provider
    try:
        llm_model = _resolve_model(env_provider, env_model)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    # Load MCP + CLI integration tools once (shared across all lanes).
    await _refresh_integration_tools()

    lane_manager = LaneManager(config, create_loop=_create_agent_loop)
    lane_manager.discord_broadcast_factory = _discord_channels_for_agent

    cron_registry = CronRegistry(config, lane_manager, router)
    cron_registry.load_all(scheduler)

    heartbeat_mgr = HeartbeatManager(config, lane_manager, router)
    await heartbeat_mgr.start()

    scheduler.start()

    # Pre-warm lanes for http sources so TUI streams connect instantly
    for source_id, source in config.sources.items():
        if source.source_type == "http":
            try:
                ghost = GatewayEvent(
                    source_id=source_id, source_type="http", payload={}
                )
                session_id = router.resolve(ghost)
                lane_manager._get_or_create(session_id)
                logger.info("http_lane_prewarmed",
                            source=source_id, session=session_id)
            except Exception:
                logger.warning("http_lane_prewarm_failed", source=source_id)

    logger.info(
        "gateway_started",
        agents=list(config.agents.keys()),
        sources=list(config.sources.keys()),
        integration_tools=len(_integration_tools),
    )

    # Clean up any plans left over from a previous crash.
    _purge_all_plans(workspace_root)

    yield

    scheduler.shutdown(wait=False)
    await heartbeat_mgr.stop()
    await lane_manager.shutdown()
    for adapter in _mcp_adapters:
        try:
            await adapter.close()
        except Exception as exc:
            logger.warning("mcp_close_error", error=str(exc))
    _mcp_adapters.clear()
    _integration_tools.clear()
    # Plans are ephemeral — delete them on every shutdown.
    _purge_all_plans(workspace_root)
    logger.info("gateway_stopped")


app = FastAPI(title="Proxi Gateway", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Shared intake
# ---------------------------------------------------------------------------
async def intake(adapter: TelegramAdapter | WhatsAppAdapter | DiscordAdapter, raw: dict) -> None:
    event = await adapter.parse(raw)
    if event is None:
        return
    event.session_id = router.resolve(event)
    await lane_manager.route(event)


def _discord_source() -> Any:
    source = config.sources.get("discord")
    if source is None or source.source_type not in ("discord", "channel"):
        raise HTTPException(
            status_code=404, detail="Discord source is not configured")
    return source


def _discord_channel_id(raw: dict[str, Any]) -> str:
    channel_id = raw.get("channel_id")
    if not channel_id and isinstance(raw.get("channel"), dict):
        channel_id = raw["channel"].get("id")
    return str(channel_id or "").strip()


def _discord_user_id(raw: dict[str, Any]) -> str:
    author = raw.get("author")
    if not isinstance(author, dict):
        return ""
    return str(author.get("id") or "").strip()


def _sanitize_session_token(value: str, fallback: str) -> str:
    cleaned = "".join(ch for ch in str(value or "")
                      if ch.isalnum() or ch in ("-", "_"))
    return cleaned or fallback


def _discord_agent_for_channel(source: Any, channel_id: str) -> str:
    overrides = source.extras.get("discord_agent_overrides", {})
    if isinstance(overrides, dict):
        override = str(overrides.get(channel_id, "")).strip()
        if override and override in config.agents:
            return override
    return source.target_agent


# Tracks channel_id → agent_id for every Discord channel that has sent a message.
# Populated at runtime so cron/heartbeat/webhook can broadcast back to active channels.
_discord_active_channels: dict[str, str] = {}


def _record_discord_channel(channel_id: str, agent_id: str) -> None:
    if channel_id:
        _discord_active_channels[channel_id] = agent_id


def _discord_channels_for_agent(agent_id: str) -> list[Any]:
    """Return DiscordReplyChannel instances for all channels currently mapped to *agent_id*."""
    from proxi.gateway.channels.discord import DiscordReplyChannel
    return [
        DiscordReplyChannel(destination=ch)
        for ch, ag in _discord_active_channels.items()
        if ag == agent_id
    ]


def _resolve_discord_session(source: Any, raw: dict[str, Any]) -> str:
    channel_id = _discord_channel_id(raw)
    user_id = _discord_user_id(raw)

    agent_id = _discord_agent_for_channel(source, channel_id)
    if agent_id not in config.agents:
        raise HTTPException(
            status_code=400, detail=f"Unknown Discord target agent: {agent_id}")

    mode = str(source.extras.get(
        "discord_session_mode", "fixed")).strip().lower()
    base_session = str(source.target_session or "").strip()
    agent_default = config.agents[agent_id].default_session

    if mode == "fixed":
        session_name = base_session or agent_default
    elif mode == "user":
        base = base_session or "discord"
        session_name = f"{base}-ch-{_sanitize_session_token(channel_id, 'unknown')}-u-{_sanitize_session_token(user_id, 'unknown')}"
    else:
        base = base_session or "discord"
        session_name = f"{base}-ch-{_sanitize_session_token(channel_id, 'unknown')}"

    return f"{agent_id}/{session_name}"


def _set_discord_channel_agent(channel_id: str, agent_id: str) -> None:
    raw = _load_gateway_raw_config()
    sources = raw["sources"]
    existing = sources.get("discord")
    if existing is None:
        raise HTTPException(
            status_code=404, detail="Discord source is not configured")
    if not isinstance(existing, dict):
        raise HTTPException(
            status_code=500, detail="Discord source config is invalid")

    overrides = existing.get("discord_agent_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    overrides[str(channel_id)] = agent_id
    existing["discord_agent_overrides"] = overrides
    sources["discord"] = existing
    _persist_and_reload_gateway_config(raw)


async def _send_discord_message(event: GatewayEvent, text: str) -> None:
    if event.reply_channel is None:
        return
    await event.reply_channel.send(text)


# ---------------------------------------------------------------------------
# Channel webhook endpoints
# ---------------------------------------------------------------------------
@app.post("/channels/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    await verify_telegram_signature(request)
    raw = await request.json()

    if "callback_query" in raw:
        cq = raw["callback_query"]
        ghost = GatewayEvent(
            source_id="telegram", source_type="telegram", payload={}
        )
        session_id = router.resolve(ghost)
        await lane_manager.resume(session_id, form_answer=cq)
    else:
        await intake(TelegramAdapter(), raw)
    return {"ok": True}


@app.get("/channels/whatsapp/webhook")
async def whatsapp_verify(
    hub_mode: str = "",
    hub_challenge: str = "",
    hub_verify_token: str = "",
) -> int | dict[str, str]:
    expected = os.environ.get("WA_VERIFY_TOKEN", "")
    if hub_verify_token != expected:
        raise HTTPException(
            status_code=403, detail="Verification token mismatch")
    return int(hub_challenge)


@app.post("/channels/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> dict[str, str]:
    await verify_whatsapp_signature(request)
    await intake(WhatsAppAdapter(), await request.json())
    return {"status": "ok"}


@app.post("/channels/discord/webhook")
async def discord_webhook(request: Request) -> dict[str, Any]:
    await verify_discord_signature(request)
    raw_payload = await request.json()
    if not isinstance(raw_payload, dict):
        raise HTTPException(
            status_code=400, detail="Discord payload must be an object")

    source = _discord_source()
    command_prefix = str(source.extras.get(
        "discord_command_prefix", "/proxi") or "/proxi")
    allow_plain = bool(source.extras.get("discord_allow_plain", False))

    event = await DiscordAdapter(
        command_prefix=command_prefix,
        allow_plain=allow_plain,
    ).parse(raw_payload)

    if event is None:
        return {"ok": True, "ignored": True}

    command = event.payload.get("command", {})
    action = str(command.get("action", "start")).strip().lower()
    session_id = _resolve_discord_session(source, raw_payload)

    if action == "help":
        await _send_discord_message(
            event,
            "Proxi Discord commands:\n"
            f"{command_prefix} <task>\n"
            f"{command_prefix} abort\n"
            f"{command_prefix} status\n"
            f"{command_prefix} switch <agent_id>",
        )
        return {"ok": True, "action": "help"}

    if action == "status":
        lane = lane_manager.get_lane(session_id)
        if lane is None:
            await _send_discord_message(event, f"Session {session_id}: idle (not created yet).")
        else:
            await _send_discord_message(
                event,
                f"Session {session_id}: running={lane.is_running}, queue_depth={lane.queue_depth}",
            )
        return {"ok": True, "action": "status", "session_id": session_id}

    if action == "abort":
        lane = lane_manager.get_lane(session_id)
        if lane is None:
            await _send_discord_message(event, f"No active lane for {session_id}.")
            return {"ok": True, "action": "abort", "session_id": session_id, "aborted": False}
        await lane.abort()
        await _send_discord_message(event, f"Aborted active run for {session_id}.")
        return {"ok": True, "action": "abort", "session_id": session_id, "aborted": True}

    if action == "switch":
        next_agent_id = str(command.get("agent_id", "")).strip()
        if not next_agent_id:
            raise HTTPException(
                status_code=400, detail="switch command requires agent id")
        if next_agent_id not in config.agents:
            raise HTTPException(
                status_code=404, detail=f"Unknown agent: {next_agent_id}")

        channel_id = _discord_channel_id(raw_payload)
        if not channel_id:
            raise HTTPException(
                status_code=400, detail="Discord channel_id is required for switch")

        _set_discord_channel_agent(channel_id, next_agent_id)
        _record_discord_channel(channel_id, next_agent_id)
        source = _discord_source()
        switched_session_id = _resolve_discord_session(source, raw_payload)
        lane_manager._get_or_create(switched_session_id)
        await _send_discord_message(
            event,
            f"Switched this channel to agent {next_agent_id}. Session: {switched_session_id}",
        )
        return {
            "ok": True,
            "action": "switch",
            "agent_id": next_agent_id,
            "session_id": switched_session_id,
        }

    if action != "start":
        raise HTTPException(
            status_code=400, detail=f"Unsupported Discord command action: {action}")

    task = str(event.payload.get("text", "")).strip()
    if not task:
        await _send_discord_message(event, f"Provide a task after {command_prefix}.")
        return {"ok": True, "ignored": True, "reason": "empty_task"}

    event.session_id = session_id
    channel_id = _discord_channel_id(raw_payload)
    agent_id = session_id.split("/", 1)[0]
    _record_discord_channel(channel_id, agent_id)
    await lane_manager.route(event)
    return {"ok": True, "action": "start", "queued": True, "session_id": session_id}


@app.post("/channels/discord/deregister")
async def discord_deregister(request: Request) -> dict[str, bool]:
    """Called by the Discord relay on shutdown to stop cron/webhook broadcasts to Discord."""
    source = config.sources.get("discord")
    if source is not None:
        await verify_discord_signature(request)
    _discord_active_channels.clear()
    logger.info("discord_active_channels_cleared")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Generic inbound webhook
# ---------------------------------------------------------------------------
@app.post("/channels/webhook/{source_id}")
async def generic_webhook(source_id: str, request: Request) -> dict[str, bool]:
    source = config.sources.get(source_id)
    if not source or source.source_type != "webhook":
        raise HTTPException(status_code=404, detail="Unknown webhook source")

    await verify_webhook_hmac(request, source)
    try:
        raw_payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Webhook payload must be valid JSON") from exc

    raw = raw_payload if isinstance(raw_payload, dict) else {
        "_raw": raw_payload}

    event = build_webhook_event(source, raw)
    event.session_id = router.resolve(event)
    await lane_manager.route(event)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Direct invocation (HTTP) — synchronous, waits for response
# ---------------------------------------------------------------------------
class InvokeRequest(BaseModel):
    message: str
    session_id: str = ""
    agent_id: str = ""


@app.post("/v1/invoke", dependencies=[Depends(verify_bearer_token)])
async def invoke(body: InvokeRequest) -> dict[str, str]:
    """One-shot: send a message, get a response synchronously."""
    session_id = body.session_id
    if not session_id:
        if body.agent_id and body.agent_id in config.agents:
            agent = config.agents[body.agent_id]
            session_id = f"{agent.agent_id}/{agent.default_session}"
        else:
            session_id = router.resolve_default()

    event, reply = build_http_event(body.message, session_id=session_id)
    await lane_manager.route(event)
    response_text = await reply.collect(timeout=300.0)
    return {"response": response_text}


# ---------------------------------------------------------------------------
# TUI session endpoints — non-blocking send + SSE stream
# ---------------------------------------------------------------------------
class SendRequest(BaseModel):
    message: str = ""
    form_answer: dict[str, Any] | None = None


@app.post("/v1/sessions/{session_id:path}/send")
async def send_to_session(session_id: str, body: SendRequest, request: Request) -> dict[str, str]:
    """Non-blocking: enqueue a message or form answer, return event_id immediately."""
    if body.form_answer is not None:
        await lane_manager.resume(session_id, form_answer=body.form_answer)
        return {"event_id": "", "status": "form_answer_injected"}

    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message required")

    lane = lane_manager.get_lane(session_id)
    if lane is not None and lane.try_resolve_pending_form_with_text(msg):
        return {"event_id": "", "status": "form_answer_injected"}

    # Re-evaluate integration toggles before each task (mirrors bridge behaviour).
    await _refresh_integration_tools()

    # Identify the caller: React frontend sends X-Proxi-Source: react.
    # Otherwise fall back to tui (if configured) or http.
    proxi_source_header = request.headers.get("X-Proxi-Source", "").strip().lower()
    if proxi_source_header == "react":
        source_id = "react"
    else:
        source_id = "tui"
        if config.sources.get(source_id) is None:
            source_id = "http"

    event = GatewayEvent(
        source_id=source_id,
        source_type="http",
        payload={"text": msg},
        reply_channel=HttpNoopReplyChannel(destination=f"{source_id}:{session_id}"),
        session_id=session_id,
        priority=0,
    )
    await lane_manager.route(event)
    return {"event_id": event.event_id}


_SSE_KEEPALIVE_INTERVAL = 15  # seconds


@app.get("/v1/sessions/{session_id:path}/stream")
async def stream_session(session_id: str, subscriber: str = Query(default="sse")) -> StreamingResponse:
    """SSE stream of agent output for a session.

    ``subscriber`` identifies the client type (e.g. 'tui', 'react') so multiple
    clients can connect to the same session simultaneously without stomping each other.
    """
    lane = lane_manager.get_lane(session_id)
    if lane is None:
        try:
            lane = lane_manager._get_or_create(session_id)
        except Exception:
            try:
                session_id = router.resolve_default()
                lane = lane_manager._get_or_create(session_id)
            except Exception:
                raise HTTPException(status_code=404, detail="Unknown session")

    sse = HttpSseReplyChannel(destination=f"sse:{session_id}:{subscriber}")
    form_bridge = HttpFormBridge(sse)
    lane.attach_sse(sse, subscriber, form_bridge)

    await sse.send_event({"type": "ready"})

    parts = session_id.split("/", 1)
    agent_id = parts[0] if parts else session_id
    session_name = parts[1] if len(parts) > 1 else "main"
    await sse.send_event({
        "type": "boot_complete",
        "agentId": agent_id,
        "sessionId": session_id,
    })

    async def event_generator():
        try:
            async for item in sse.stream():
                yield f"data: {json.dumps(item)}\n\n"
        except Exception:
            pass
        finally:
            lane.detach_sse(sse, subscriber)

    async def keepalive_generator():
        """Merge data events with periodic SSE comments to keep the connection alive."""
        data_gen = event_generator()
        pending_data: asyncio.Task[str] | None = None
        try:
            while True:
                if pending_data is None:
                    pending_data = asyncio.ensure_future(data_gen.__anext__())
                try:
                    chunk = await asyncio.wait_for(
                        asyncio.shield(pending_data),
                        timeout=_SSE_KEEPALIVE_INTERVAL,
                    )
                    pending_data = None
                    yield chunk
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except StopAsyncIteration:
            pass
        except GeneratorExit:
            if pending_data and not pending_data.done():
                pending_data.cancel()
            raise

    return StreamingResponse(
        keepalive_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Lane inspection (admin / debug)
# ---------------------------------------------------------------------------
@app.get("/v1/lanes", dependencies=[Depends(verify_bearer_token)])
async def list_lanes() -> list[dict[str, Any]]:
    return lane_manager.list_lanes()


@app.get("/v1/lanes/{session_id:path}", dependencies=[Depends(verify_bearer_token)])
async def get_lane(session_id: str) -> dict[str, Any]:
    lane = lane_manager.get_lane(session_id)
    if lane is None:
        raise HTTPException(status_code=404, detail="Lane not found")
    return {
        "session_id": lane.session_id,
        "queue_depth": lane.queue_depth,
        "running": lane.is_running,
    }


# ---------------------------------------------------------------------------
# Integration management
# ---------------------------------------------------------------------------
@app.get("/v1/integrations")
async def list_integrations_endpoint() -> dict[str, Any]:
    """List all integrations with their enabled/disabled status."""
    from proxi.security.key_store import list_integrations as _list_integrations

    records = _list_integrations()
    return {
        "integrations": [
            {"name": r.integration_name, "enabled": r.enabled}
            for r in sorted(records, key=lambda r: r.integration_name)
        ]
    }


@app.post("/v1/integrations/{integration_name}/toggle")
async def toggle_integration_endpoint(integration_name: str) -> dict[str, Any]:
    """Toggle an integration between enabled and disabled."""
    from proxi.security.key_store import (
        enable_integration as _enable_integration,
        is_integration_enabled,
    )

    currently_enabled = is_integration_enabled(integration_name)
    new_state = not currently_enabled
    _enable_integration(integration_name, enabled=new_state)

    # Immediately refresh MCP-type integration tools so the change takes effect.
    await _refresh_integration_tools()

    return {"name": integration_name, "enabled": new_state}


# ---------------------------------------------------------------------------
# Working directory management
# ---------------------------------------------------------------------------
@app.get("/v1/working-dir")
async def get_working_dir_endpoint(agent_id: str | None = None) -> dict[str, str]:
    """Return the effective working directory for the given agent (or the global default)."""
    if agent_id:
        return {"path": str(_agent_working_dirs.get(agent_id, _working_dir))}
    return {"path": str(_working_dir)}


class SetWorkingDirRequest(BaseModel):
    path: str
    agent_id: str | None = None


@app.post("/v1/working-dir")
async def set_working_dir_endpoint(body: SetWorkingDirRequest) -> dict[str, str]:
    """Set a new working directory and re-root coding tools on active lanes.

    If agent_id is provided, only that agent's runtime working dir is updated.
    Otherwise the global fallback is updated and all lanes are re-rooted.
    """
    global _working_dir
    raw = (body.path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    new_dir = Path(raw).expanduser().resolve()
    if not new_dir.exists():
        raise HTTPException(
            status_code=400, detail=f"Path does not exist: {new_dir}")
    if not new_dir.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Path is not a directory: {new_dir}")

    if body.agent_id:
        _agent_working_dirs[body.agent_id] = new_dir
        if lane_manager is not None:
            lane_manager.sync_coding_tools_to_agent_loops(
                body.agent_id, new_dir)
    else:
        _working_dir = new_dir
        if lane_manager is not None:
            lane_manager.sync_coding_tools_to_loops(new_dir)

    logger.info("working_dir_changed", path=str(
        new_dir), agent_id=body.agent_id)
    return {"path": str(new_dir)}


# ---------------------------------------------------------------------------
# Agent management
# ---------------------------------------------------------------------------
@app.get("/v1/agents")
async def list_agents_endpoint() -> dict[str, Any]:
    """List all agents configured in gateway.yml."""
    agents = [
        {
            "agent_id": a.agent_id,
            "soul_path": str(a.soul_path),
            "default_session": a.default_session,
        }
        for a in config.agents.values()
    ]
    return {"agents": agents}


class CreateAgentRequest(BaseModel):
    name: str
    persona: str = "Helpful, patient, and clear."
    agent_id: str | None = None
    default_session: str = "main"


@app.post("/v1/agents")
async def create_agent_endpoint(body: CreateAgentRequest) -> dict[str, Any]:
    """Create agent directories, Soul.md, and register the agent in ``gateway.yml``."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    wm = WorkspaceManager(root=_workspace_root())
    wm.ensure_global_system_prompt()
    aid = body.agent_id.strip() if body.agent_id else None
    try:
        info = wm.create_agent(
            name=name,
            persona=(body.persona or "").strip(
            ) or "Helpful, patient, and clear.",
            agent_id=aid,
            sync_gateway=True,
            default_session=(body.default_session or "").strip() or "main",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _reload_gateway_config()
    logger.info("agent_created_via_api", agent_id=info.agent_id)
    return {
        "agent_id": info.agent_id,
        "soul_path": str((info.path / "Soul.md").resolve()),
    }


@app.delete("/v1/agents/{agent_id}")
async def delete_agent_endpoint(agent_id: str) -> dict[str, Any]:
    """Remove an agent from ``gateway.yml``, delete ``agents/<id>/``, and stop its lanes."""
    if lane_manager is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    aid = agent_id.strip()
    if not aid:
        raise HTTPException(status_code=400, detail="agent_id required")

    wm = WorkspaceManager(root=_workspace_root())
    try:
        await lane_manager.remove_lanes_for_agent(aid)
        wm.delete_agent(aid)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _reload_gateway_config()
    logger.info("agent_deleted_via_api", agent_id=aid)
    return {"status": "deleted", "agent_id": aid}


@app.post("/v1/sessions/{session_id:path}/branch")
async def branch_session_endpoint(session_id: str) -> dict[str, Any]:
    """Clone the agent owning session_id into a new agent, seeding it with the current history.

    The new agent copies Soul.md and config.yaml from the parent and inherits
    the session's history.jsonl so the LLM prompt cache hits immediately.

    Returns: { agent_id, session_id }
    """
    if lane_manager is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    parts = session_id.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400, detail="Invalid session_id format")
    agent_id, session_name = parts
    agent_cfg = config.agents.get(agent_id)
    if agent_cfg is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown agent: {agent_id}")
    source_history_path = config.session_history_path(agent_id, session_name)
    working_dir_str = str(
        _agent_working_dirs[agent_id]) if agent_id in _agent_working_dirs else None
    wm = WorkspaceManager(root=_workspace_root())
    try:
        new_agent = wm.branch_agent(
            parent_agent_id=agent_id,
            source_history_path=source_history_path,
            default_session=agent_cfg.default_session,
            working_dir=working_dir_str,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _reload_gateway_config()
    new_session_id = f"{new_agent.agent_id}/{agent_cfg.default_session}"
    lane_manager._get_or_create(new_session_id)
    logger.info("agent_branched", parent=agent_id,
                new_agent=new_agent.agent_id)
    return {"agent_id": new_agent.agent_id, "session_id": new_session_id}


@app.post("/v1/sessions/{session_id:path}/btw")
async def create_btw_session_endpoint(session_id: str) -> dict[str, Any]:
    """Create a side-session on the same agent that inherits the current history.

    The new session copies the parent's history.jsonl so the LLM prompt cache
    is warm. The original session is untouched.

    Returns: { btw_session_id, return_session_id }
    """
    if lane_manager is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    parts = session_id.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400, detail="Invalid session_id format")
    agent_id, session_name = parts
    if agent_id not in config.agents:
        raise HTTPException(
            status_code=404, detail=f"Unknown agent: {agent_id}")
    from datetime import datetime, timezone
    btw_name = "btw-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    btw_session_id = f"{agent_id}/{btw_name}"
    source_history_path = config.session_history_path(agent_id, session_name)
    wm = WorkspaceManager(root=_workspace_root())
    wm.create_named_session(
        AgentInfo(agent_id=agent_id, path=wm.agents_dir / agent_id),
        btw_name,
        source_history_path=source_history_path,
    )
    lane_manager._get_or_create(btw_session_id)
    logger.info("btw_session_created", agent=agent_id,
                btw_session=btw_session_id, return_session=session_id)
    return {"btw_session_id": btw_session_id, "return_session_id": session_id}


@app.delete("/v1/sessions/{session_id:path}")
async def delete_session_endpoint(session_id: str) -> dict[str, Any]:
    """Stop the lane for session_id and delete its directory from disk."""
    if lane_manager is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    parts = session_id.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400, detail="Invalid session_id format")
    agent_id, session_name = parts
    await lane_manager.remove_lane(session_id)
    wm = WorkspaceManager(root=_workspace_root())
    wm.delete_session(agent_id, session_name)
    logger.info("session_deleted", session_id=session_id)
    return {"status": "deleted", "session_id": session_id}


class SwitchAgentRequest(BaseModel):
    agent_id: str


class LlmConfigUpdateRequest(BaseModel):
    provider: str
    model: str = ""


class CronJobUpsertRequest(BaseModel):
    schedule: str
    prompt: str
    target_agent: str
    priority: int = 0
    paused: bool = False
    target_session: str = ""


class CronPauseRequest(BaseModel):
    paused: bool


class WebhookUpsertRequest(BaseModel):
    prompt_template: str = ""
    target_agent: str
    priority: int = 0
    paused: bool = False
    target_session: str = ""
    secret_env: str = ""


class WebhookPauseRequest(BaseModel):
    paused: bool


@app.post("/v1/sessions/switch")
async def switch_agent_endpoint(body: SwitchAgentRequest) -> dict[str, Any]:
    """Switch the TUI to a different agent.

    Returns the new session_id the TUI should reconnect to.
    """
    agent = config.agents.get(body.agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown agent: {body.agent_id}")
    new_session_id = f"{agent.agent_id}/{agent.default_session}"
    lane_manager._get_or_create(new_session_id)
    return {"session_id": new_session_id, "agent_id": agent.agent_id}


@app.get("/v1/llm-config")
async def get_llm_config_endpoint() -> dict[str, Any]:
    return {
        "provider": llm_provider,
        "model": llm_model,
        "providers": sorted(SUPPORTED_LLM_MODELS.keys()),
        "models": SUPPORTED_LLM_MODELS,
        "model_limits": LLM_MODEL_LIMITS,
        "defaults": DEFAULT_LLM_MODELS,
    }


@app.put("/v1/llm-config")
async def update_llm_config_endpoint(body: LlmConfigUpdateRequest) -> dict[str, Any]:
    global llm_provider, llm_model

    try:
        provider = _normalize_provider(body.provider)
        model = _resolve_model(provider, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    llm_provider = provider
    llm_model = model

    if lane_manager is not None:
        await lane_manager.reset_all_loops()

    logger.info("llm_config_updated", provider=provider, model=model)
    return {
        "provider": llm_provider,
        "model": llm_model,
        "providers": sorted(SUPPORTED_LLM_MODELS.keys()),
        "models": SUPPORTED_LLM_MODELS,
        "model_limits": LLM_MODEL_LIMITS,
        "defaults": DEFAULT_LLM_MODELS,
    }


@app.get("/v1/cron-jobs")
async def list_cron_jobs_endpoint() -> dict[str, Any]:
    """List cron jobs defined in ``gateway.yml`` sources."""
    jobs: list[dict[str, Any]] = []
    for source_id, source in config.sources.items():
        if source.source_type != "cron":
            continue
        jobs.append(
            {
                "source_id": source_id,
                "schedule": source.schedule,
                "prompt": source.prompt,
                "target_agent": source.target_agent,
                "target_session": source.target_session,
                "priority": source.priority,
                "paused": source.paused,
            }
        )

    jobs.sort(key=lambda item: item["source_id"])
    return {"cron_jobs": jobs}


@app.get("/v1/cron-capabilities")
async def cron_capabilities_endpoint() -> dict[str, Any]:
    """Return cron parser capabilities for UI compatibility checks."""
    supports_six_field = True
    try:
        _parse_cron("*/15 * * * * *")
    except ValueError:
        supports_six_field = False

    return {
        "supports_six_field": supports_six_field,
        "accepted_formats": [
            "minute hour day month day_of_week",
            "second minute hour day month day_of_week",
        ] if supports_six_field else [
            "minute hour day month day_of_week",
        ],
    }


@app.put("/v1/cron-jobs/{source_id}")
async def upsert_cron_job_endpoint(source_id: str, body: CronJobUpsertRequest) -> dict[str, Any]:
    """Create or update a cron source in ``gateway.yml`` and hot-reload scheduler jobs."""
    sid = source_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="source_id is required")

    schedule = (body.schedule or "").strip()
    prompt = (body.prompt or "").strip()
    target_agent = (body.target_agent or "").strip()
    target_session = (body.target_session or "").strip()

    if not schedule:
        raise HTTPException(status_code=400, detail="schedule is required")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    if not target_agent:
        raise HTTPException(status_code=400, detail="target_agent is required")
    if target_agent not in config.agents:
        raise HTTPException(
            status_code=400, detail=f"Unknown agent: {target_agent}")
    if body.priority < 0 or body.priority > 5:
        raise HTTPException(
            status_code=400, detail="priority must be between 0 and 5")

    try:
        _parse_cron(schedule)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw = _load_gateway_raw_config()
    sources = raw["sources"]

    existing = sources.get(sid)
    if existing is None:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    existing["type"] = "cron"
    existing["schedule"] = schedule
    existing["prompt"] = prompt
    existing["target_agent"] = target_agent
    existing["priority"] = int(body.priority)
    existing["paused"] = bool(body.paused)
    if target_session:
        existing["target_session"] = target_session
    elif "target_session" in existing:
        del existing["target_session"]

    sources[sid] = existing

    _persist_and_reload_gateway_config(raw)

    return {
        "source_id": sid,
        "schedule": schedule,
        "prompt": prompt,
        "target_agent": target_agent,
        "target_session": target_session,
        "priority": int(body.priority),
        "paused": bool(body.paused),
    }


@app.post("/v1/cron-jobs/{source_id}/pause")
async def pause_cron_job_endpoint(source_id: str, body: CronPauseRequest) -> dict[str, Any]:
    """Pause or resume a cron source and hot-reload scheduler jobs."""
    sid = source_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="source_id is required")

    raw = _load_gateway_raw_config()
    sources = raw["sources"]
    existing = sources.get(sid)
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"Cron source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "cron":
        raise HTTPException(
            status_code=400, detail=f"Source is not a cron job: {sid}")

    existing["paused"] = bool(body.paused)
    sources[sid] = existing

    _persist_and_reload_gateway_config(raw)
    return {"status": "updated", "source_id": sid, "paused": bool(body.paused)}


@app.delete("/v1/cron-jobs/{source_id}")
async def delete_cron_job_endpoint(source_id: str) -> dict[str, Any]:
    """Delete a cron source from ``gateway.yml`` and hot-reload scheduler jobs."""
    sid = source_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="source_id is required")

    raw = _load_gateway_raw_config()
    sources = raw["sources"]
    existing = sources.get(sid)
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"Cron source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "cron":
        raise HTTPException(
            status_code=400, detail=f"Source is not a cron job: {sid}")

    del sources[sid]
    _persist_and_reload_gateway_config(raw)
    return {"status": "deleted", "source_id": sid}


# Webhook Sources
# ---------------------------------------------------------------------------
@app.get("/v1/webhooks")
async def list_webhooks_endpoint() -> dict[str, Any]:
    """List webhook sources defined in ``gateway.yml``."""
    webhooks: list[dict[str, Any]] = []
    for source_id, source in config.sources.items():
        if source.source_type != "webhook":
            continue
        webhooks.append(
            {
                "source_id": source_id,
                "prompt_template": source.prompt_template or "",
                "target_agent": source.target_agent,
                "target_session": source.target_session,
                "priority": source.priority,
                "paused": source.paused,
                "has_secret": bool(source.secret_env),
                "secret_env": source.secret_env or "",
            }
        )

    webhooks.sort(key=lambda item: item["source_id"])
    return {"webhooks": webhooks}


@app.put("/v1/webhooks/{source_id}")
async def upsert_webhook_endpoint(source_id: str, body: WebhookUpsertRequest) -> dict[str, Any]:
    """Create or update a webhook source in ``gateway.yml``."""
    sid = source_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="source_id is required")

    target_agent = (body.target_agent or "").strip()
    target_session = (body.target_session or "").strip()
    secret_env = (body.secret_env or "").strip()

    if not target_agent:
        raise HTTPException(status_code=400, detail="target_agent is required")
    if not secret_env:
        raise HTTPException(
            status_code=400, detail="secret_env is required for webhook security")
    if target_agent not in config.agents:
        raise HTTPException(
            status_code=400, detail=f"Unknown agent: {target_agent}")
    if body.priority < 0 or body.priority > 5:
        raise HTTPException(
            status_code=400, detail="priority must be between 0 and 5")

    raw = _load_gateway_raw_config()
    sources = raw["sources"]

    existing = sources.get(sid)
    if existing is None:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    existing["type"] = "webhook"
    existing["target_agent"] = target_agent
    existing["priority"] = int(body.priority)
    existing["paused"] = bool(body.paused)

    if body.prompt_template:
        existing["prompt_template"] = body.prompt_template
    elif "prompt_template" in existing:
        del existing["prompt_template"]

    if target_session:
        existing["target_session"] = target_session
    elif "target_session" in existing:
        del existing["target_session"]

    existing["secret_env"] = secret_env

    sources[sid] = existing

    _persist_and_reload_gateway_config(raw)

    return {
        "source_id": sid,
        "prompt_template": body.prompt_template or "",
        "target_agent": target_agent,
        "target_session": target_session,
        "priority": int(body.priority),
        "paused": bool(body.paused),
        "has_secret": True,
        "secret_env": secret_env,
    }


@app.post("/v1/webhooks/{source_id}/pause")
async def pause_webhook_endpoint(source_id: str, body: WebhookPauseRequest) -> dict[str, Any]:
    """Pause or resume a webhook source."""
    sid = source_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="source_id is required")

    raw = _load_gateway_raw_config()
    sources = raw["sources"]
    existing = sources.get(sid)
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"Webhook source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "webhook":
        raise HTTPException(
            status_code=400, detail=f"Source is not a webhook: {sid}")

    existing["paused"] = bool(body.paused)
    sources[sid] = existing

    _persist_and_reload_gateway_config(raw)
    return {"status": "updated", "source_id": sid, "paused": bool(body.paused)}


@app.delete("/v1/webhooks/{source_id}")
async def delete_webhook_endpoint(source_id: str) -> dict[str, Any]:
    """Delete a webhook source from ``gateway.yml``."""
    sid = source_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="source_id is required")

    raw = _load_gateway_raw_config()
    sources = raw["sources"]
    existing = sources.get(sid)
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"Webhook source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "webhook":
        raise HTTPException(
            status_code=400, detail=f"Source is not a webhook: {sid}")

    del sources[sid]
    _persist_and_reload_gateway_config(raw)
    return {"status": "deleted", "source_id": sid}


# ---------------------------------------------------------------------------
# Abort (cancel running task in a lane)
# ---------------------------------------------------------------------------
@app.post("/v1/sessions/{session_id:path}/abort")
async def abort_session(session_id: str) -> dict[str, str]:
    """Cancel the running agent task in a lane."""
    lane = lane_manager.get_lane(session_id)
    if lane is None:
        raise HTTPException(status_code=404, detail="Lane not found")
    await lane.abort()
    return {"status": "aborted"}


@app.post("/v1/sessions/{session_id:path}/plan/accept")
async def accept_plan(session_id: str) -> dict[str, str]:
    """Accept the current plan: save to plans/ dir, exit plan mode, and auto-execute."""
    import re
    from datetime import datetime

    lane = lane_manager.get_lane(session_id) if lane_manager else None
    if lane is None:
        raise HTTPException(status_code=404, detail="Lane not found")
    if lane._state is None or lane._state.workspace is None:
        raise HTTPException(status_code=400, detail="No active session workspace")

    # Read from active_plan_path (plans/in-progress.md) if set, else session plan.md
    _pfile = lane._state.workspace.active_plan_path or lane._state.workspace.plan_path
    plan_path = Path(_pfile)
    if not plan_path.exists() or plan_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="No plan to accept")

    plan_content = plan_path.read_text(encoding="utf-8")

    # Derive a slug from the first # heading, fallback to "plan"
    slug = "plan"
    for line in plan_content.splitlines():
        heading = line.lstrip("#").strip()
        if heading:
            slug = re.sub(r"[^a-z0-9]+", "-", heading.lower())[:40].strip("-")
            break

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workspace_root = Path(lane._state.workspace.workspace_root)
    agent_id = lane._state.workspace.agent_id
    plans_dir = workspace_root / "agents" / agent_id / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    saved_path = plans_dir / f"{timestamp}_{slug}.md"

    # Rename in-progress.md → timestamped file (atomic on same filesystem)
    try:
        plan_path.rename(saved_path)
    except OSError:
        saved_path.write_text(plan_content, encoding="utf-8")
        plan_path.unlink(missing_ok=True)

    # Exit plan mode and clear the active plan path; keep reasoning_effort at "medium"
    # for the execution run (complex plan → deserves better reasoning throughout).
    lane._state.plan_mode = False
    lane._state.reasoning_effort = "medium"
    lane._state.workspace.active_plan_path = None
    lane.workspace_config.active_plan_path = None

    # Inject plan content as the next user turn so the agent auto-executes
    execute_message = f"Execute the following plan:\n\n{plan_content}"

    if lane._sse_channels:
        await lane._broadcast_sse({
            "type": "status_update",
            "label": "Executing plan",
            "status": "running",
            "tui_abortable": True,
        })

    # Route the execution message through the lane (async background task)
    event = GatewayEvent(
        source_id="tui",
        source_type="http",
        payload={"text": execute_message},
    )
    asyncio.create_task(lane._dispatch(event))

    return {"status": "accepted", "saved_to": str(saved_path)}


@app.post("/v1/sessions/{session_id:path}/plan/reject")
async def reject_plan(session_id: str) -> dict[str, str]:
    """Reject the current plan: clear plan.md and exit plan mode."""
    lane = lane_manager.get_lane(session_id) if lane_manager else None
    if lane is None:
        raise HTTPException(status_code=404, detail="Lane not found")
    if lane._state is None or lane._state.workspace is None:
        raise HTTPException(status_code=400, detail="No active session workspace")

    # Delete in-progress.md (plans/ dir) if it exists, otherwise clear session plan.md
    _pfile = lane._state.workspace.active_plan_path or lane._state.workspace.plan_path
    plan_path = Path(_pfile)
    try:
        plan_path.unlink(missing_ok=True)
    except Exception:
        pass

    lane._state.plan_mode = False
    lane._state.reasoning_effort = "minimal"
    lane._state.workspace.active_plan_path = None
    lane.workspace_config.active_plan_path = None

    if lane._sse_channels:
        await lane._broadcast_sse({
            "type": "text_stream",
            "content": "Plan rejected.",
        })
        await lane._broadcast_sse({
            "type": "status_update",
            "label": "Plan rejected",
            "status": "done",
            "tui_abortable": False,
        })

    return {"status": "rejected"}


@app.post("/v1/sessions/{session_id:path}/clear-history")
async def clear_session_history_endpoint(session_id: str) -> dict[str, str]:
    """Truncate session ``history.jsonl`` and reset the lane (system prompt unchanged)."""
    try:
        await lane_manager.clear_session_history(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "cleared"}


@app.get("/v1/sessions/{session_id:path}/stats")
async def get_session_stats(session_id: str) -> dict[str, Any]:
    """Return token and turn usage stats for an active session lane."""
    lane = lane_manager.get_lane(session_id)
    if lane is None:
        raise HTTPException(
            status_code=404, detail="No active lane for this session")
    b = lane.budget
    return {
        "tokens_used": b.tokens_used,
        "token_budget": b.token_budget,
        "context_window": b.context_window,
        "compaction_threshold": b.compaction_threshold,
        "turns_used": b.turns_used,
        "max_turns": b.max_turns,
    }


# ---------------------------------------------------------------------------
# User profile (debug / verification)
# ---------------------------------------------------------------------------
@app.get("/v1/profile")
async def get_profile_endpoint() -> dict[str, Any]:
    """Return the user profile as seen by the gateway."""
    record = get_user_profile()
    if not record:
        return {"profile": None}
    return {"profile": record.profile, "updated_at": record.updated_at}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "lanes": len(lane_manager.list_lanes()) if lane_manager else 0,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """``proxi-gateway`` entry point."""
    from dotenv import load_dotenv

    load_dotenv()

    log_manager = init_log_manager(base_dir="logs")
    log_manager.configure_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"), use_colors=True,
    )

    host = os.environ.get("GATEWAY_HOST", "0.0.0.0")
    port = int(os.environ.get("GATEWAY_PORT", "8765"))

    uvicorn.run(
        "proxi.gateway.server:app",
        host=host,
        port=port,
        log_level="info",
    )
