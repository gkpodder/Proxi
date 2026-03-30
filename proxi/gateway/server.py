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
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from proxi.cli.main import (
    auto_load_mcp_servers,
    create_llm_client,
    setup_sub_agents,
    setup_tools,
)
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
    verify_telegram_signature,
    verify_webhook_hmac,
    verify_whatsapp_signature,
)
from proxi.gateway.router import EventRouter
from proxi.interaction.tool import get_ask_user_question_spec
from proxi.observability.logging import get_logger, init_log_manager
from proxi.security.key_store import get_user_profile
from proxi.tools.coding import register_coding_tools
from proxi.tools.workspace_tools import ManagePlanTool, ManageTodosTool, ReadSoulTool
from proxi.workspace import WorkspaceError, WorkspaceManager

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (populated during lifespan)
# ---------------------------------------------------------------------------
config: GatewayConfig
router: EventRouter
lane_manager: LaneManager | None = None
heartbeat_mgr: HeartbeatManager
scheduler = AsyncIOScheduler()

SUPPORTED_LLM_MODELS: dict[str, list[str]] = {
    "openai": [
        "gpt-5-mini-2025-08-07",
        "gpt-5-2025-08-07",
        "gpt-4.1-mini",
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
    ],
}
DEFAULT_LLM_MODELS: dict[str, str] = {
    provider: models[0] for provider, models in SUPPORTED_LLM_MODELS.items()
}
llm_provider: str = "openai"
llm_model: str = DEFAULT_LLM_MODELS["openai"]

# MCP adapters loaded once at startup; their tools are injected into each lane.
_mcp_adapters: list[Any] = []
_mcp_tools: list[Any] = []           # live (always-loaded) MCP tools
_mcp_deferred_tools: list[Any] = []  # deferred MCP tools (loaded via search_tools)
_last_mcp_signature: str | None = None
_mcp_refresh_lock = asyncio.Lock()

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
        raise HTTPException(status_code=404, detail=f"gateway.yml not found at {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=500, detail="gateway.yml must be a YAML mapping")

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
    if requested not in allowed:
        raise ValueError(f"Unsupported model for {provider}: {requested}")
    return requested


async def _refresh_mcp_tools() -> None:
    """Reload MCP tools when the enabled-MCP set has changed."""
    global _mcp_adapters, _mcp_tools, _mcp_deferred_tools, _last_mcp_signature

    no_mcp = os.environ.get("PROXI_NO_MCP", "").lower() in ("1", "true", "yes")
    if no_mcp:
        return

    async with _mcp_refresh_lock:
        from proxi.cli.main import load_mcp_config
        from proxi.security.key_store import get_enabled_mcps

        sig_payload = {
            "enabled": sorted(get_enabled_mcps()),
            "config": load_mcp_config(),
        }
        sig = hashlib.sha256(
            json.dumps(sig_payload, sort_keys=True,
                       separators=(",", ":")).encode()
        ).hexdigest()
        if sig == _last_mcp_signature:
            return
        _last_mcp_signature = sig

        for adapter in _mcp_adapters:
            try:
                await asyncio.wait_for(adapter.close(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("mcp_close_timeout")
            except Exception as exc:
                logger.warning("mcp_close_error", error=str(exc))
        _mcp_adapters.clear()
        _mcp_tools.clear()
        _mcp_deferred_tools.clear()

        try:
            from proxi.tools.registry import ToolRegistry as _TR

            tmp_registry = _TR()
            _mcp_adapters[:] = await asyncio.wait_for(
                auto_load_mcp_servers(tmp_registry), timeout=30.0
            )
            _mcp_tools[:] = list(tmp_registry._tools.values())
            _mcp_deferred_tools[:] = list(tmp_registry._deferred_tools.values())
            logger.info(
                "mcp_refreshed",
                adapters=len(_mcp_adapters),
                tools=len(_mcp_tools),
                deferred=len(_mcp_deferred_tools),
            )
        except Exception as exc:
            logger.warning("mcp_refresh_error", error=str(exc))

        # Existing lanes keep the same AgentLoop + ToolRegistry; refresh replaces
        # global tool objects and closes old MCP stdio clients — push the new tools
        # into every active loop so toggles take effect without restarting the gateway.
        if lane_manager is not None:
            lane_manager.sync_mcp_tools_to_loops(_mcp_tools, _mcp_deferred_tools)


def _create_agent_loop(workspace_config: WorkspaceConfig) -> AgentLoop:
    """Factory called by LaneManager to create an AgentLoop per session.

    Each lane gets its own tool registry so workspace-scoped tools
    (plan, todos, soul) resolve to the correct session paths.
    MCP tools loaded at gateway startup are shared across all lanes.
    """
    llm_client = create_llm_client(provider=llm_provider, model=llm_model)

    working_dir = _agent_working_dirs.get(workspace_config.agent_id, _working_dir)

    tool_registry = setup_tools(working_directory=working_dir)
    tool_registry.register_raw_spec(get_ask_user_question_spec())
    tool_registry.register(ManagePlanTool(workspace_config))
    tool_registry.register(ManageTodosTool(workspace_config))
    tool_registry.register(ReadSoulTool(workspace_config))

    # Register coding tools based on per-agent config
    workspace_manager = WorkspaceManager(root=_workspace_root())
    agent_config = workspace_manager.read_agent_config(workspace_config.agent_id)
    coding_tier = agent_config.get("tool_sets", {}).get("coding", "live")
    register_coding_tools(tool_registry, working_dir=working_dir, tier=str(coding_tier))

    workspace_config.curr_working_dir = str(working_dir)

    for mcp_tool in _mcp_tools:
        tool_registry.register(mcp_tool)
    for mcp_tool in _mcp_deferred_tools:
        tool_registry.register_deferred(mcp_tool)
    if tool_registry.has_deferred_tools():
        from proxi.tools.call_tool_tool import CallToolTool
        tool_registry.register(CallToolTool(tool_registry))

    no_sub_agents = os.environ.get("PROXI_NO_SUB_AGENTS", "").lower() in (
        "1", "true", "yes",
    )
    sub_agent_manager = None if no_sub_agents else setup_sub_agents(llm_client)

    max_turns = int(os.environ.get("PROXI_MAX_TURNS", "100"))
    return AgentLoop(
        llm_client=llm_client,
        tool_registry=tool_registry,
        sub_agent_manager=sub_agent_manager,
        max_turns=max_turns,
        enable_reflection=True,
        workspace=workspace_config,
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    global config, router, lane_manager, heartbeat_mgr
    global _mcp_adapters, _mcp_tools
    global llm_provider, llm_model

    workspace_root = _workspace_root()
    WorkspaceManager(root=workspace_root).ensure_global_system_prompt()

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

    # Load MCP adapters once so their tools are available to all lanes.
    await _refresh_mcp_tools()

    lane_manager = LaneManager(config, create_loop=_create_agent_loop)

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
        mcp_tools=len(_mcp_tools),
    )

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
    _mcp_tools.clear()
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
async def discord_webhook(request: Request) -> dict[str, bool]:
    await intake(DiscordAdapter(), await request.json())
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
        raise HTTPException(status_code=400, detail="Webhook payload must be valid JSON") from exc

    raw = raw_payload if isinstance(raw_payload, dict) else {"_raw": raw_payload}

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
async def send_to_session(session_id: str, body: SendRequest) -> dict[str, str]:
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

    # Re-evaluate MCP toggles before each task (mirrors bridge behaviour).
    await _refresh_mcp_tools()

    # Build a lightweight event using the tui source (if configured) or http fallback
    source_id = "tui"
    source = config.sources.get(source_id)
    if source is None:
        source_id = "http"

    event = GatewayEvent(
        source_id=source_id,
        source_type="http",
        payload={"text": msg},
        reply_channel=HttpNoopReplyChannel(destination=f"tui:{session_id}"),
        session_id=session_id,
        priority=0,
    )
    await lane_manager.route(event)
    return {"event_id": event.event_id}


_SSE_KEEPALIVE_INTERVAL = 15  # seconds


@app.get("/v1/sessions/{session_id:path}/stream")
async def stream_session(session_id: str) -> StreamingResponse:
    """SSE stream of agent output for a session."""
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

    sse = HttpSseReplyChannel(destination=f"sse:{session_id}")
    form_bridge = HttpFormBridge(sse)
    lane.attach_sse(sse, form_bridge)

    await sse.send_event({"type": "ready"})

    parts = session_id.split("/", 1)
    agent_id = parts[0] if parts else session_id
    session_name = parts[1] if len(parts) > 1 else "main"
    await sse.send_event({
        "type": "boot_complete",
        "agentId": agent_id,
        "sessionId": session_name,
    })

    async def event_generator():
        try:
            async for item in sse.stream():
                yield f"data: {json.dumps(item)}\n\n"
        except Exception:
            pass
        finally:
            lane.detach_sse(sse)

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
# MCP management
# ---------------------------------------------------------------------------
@app.get("/v1/mcps")
async def list_mcps_endpoint() -> dict[str, Any]:
    """List all MCPs with their enabled/disabled status."""
    from proxi.security.key_store import list_mcps as _list_mcps

    records = _list_mcps()
    return {
        "mcps": [
            {"name": r.mcp_name, "enabled": r.enabled}
            for r in sorted(records, key=lambda r: r.mcp_name)
        ]
    }


@app.post("/v1/mcps/{mcp_name}/toggle")
async def toggle_mcp_endpoint(mcp_name: str) -> dict[str, Any]:
    """Toggle an MCP between enabled and disabled."""
    from proxi.security.key_store import enable_mcp as _enable_mcp, is_mcp_enabled

    currently_enabled = is_mcp_enabled(mcp_name)
    new_state = not currently_enabled
    _enable_mcp(mcp_name, enabled=new_state)

    # Immediately refresh loaded MCP tools so the change takes effect.
    await _refresh_mcp_tools()

    return {"name": mcp_name, "enabled": new_state}


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
        raise HTTPException(status_code=400, detail=f"Path does not exist: {new_dir}")
    if not new_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {new_dir}")

    if body.agent_id:
        _agent_working_dirs[body.agent_id] = new_dir
        if lane_manager is not None:
            lane_manager.sync_coding_tools_to_agent_loops(body.agent_id, new_dir)
    else:
        _working_dir = new_dir
        if lane_manager is not None:
            lane_manager.sync_coding_tools_to_loops(new_dir)

    logger.info("working_dir_changed", path=str(new_dir), agent_id=body.agent_id)
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
        raise HTTPException(status_code=400, detail=f"Unknown agent: {target_agent}")
    if body.priority < 0 or body.priority > 5:
        raise HTTPException(status_code=400, detail="priority must be between 0 and 5")

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
        raise HTTPException(status_code=404, detail=f"Cron source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "cron":
        raise HTTPException(status_code=400, detail=f"Source is not a cron job: {sid}")

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
        raise HTTPException(status_code=404, detail=f"Cron source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "cron":
        raise HTTPException(status_code=400, detail=f"Source is not a cron job: {sid}")

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
        raise HTTPException(status_code=400, detail="secret_env is required for webhook security")
    if target_agent not in config.agents:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {target_agent}")
    if body.priority < 0 or body.priority > 5:
        raise HTTPException(status_code=400, detail="priority must be between 0 and 5")

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
        raise HTTPException(status_code=404, detail=f"Webhook source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "webhook":
        raise HTTPException(status_code=400, detail=f"Source is not a webhook: {sid}")

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
        raise HTTPException(status_code=404, detail=f"Webhook source not found: {sid}")
    if not isinstance(existing, dict) or existing.get("type") != "webhook":
        raise HTTPException(status_code=400, detail=f"Source is not a webhook: {sid}")

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
        raise HTTPException(status_code=404, detail="No active lane for this session")
    b = lane.budget
    return {
        "tokens_used": b.tokens_used,
        "token_budget": b.token_budget,
        "context_window": b.context_window,
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
