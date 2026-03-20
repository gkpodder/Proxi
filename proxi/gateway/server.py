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
from proxi.gateway.channels.cron import CronRegistry
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
from proxi.interaction.tool import get_show_collaborative_form_spec
from proxi.observability.logging import get_logger, init_log_manager
from proxi.security.key_store import get_user_profile
from proxi.tools.workspace_tools import ManagePlanTool, ManageTodosTool, ReadSoulTool
from proxi.workspace import WorkspaceManager

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (populated during lifespan)
# ---------------------------------------------------------------------------
config: GatewayConfig
router: EventRouter
lane_manager: LaneManager | None = None
heartbeat_mgr: HeartbeatManager
scheduler = AsyncIOScheduler()

# MCP adapters loaded once at startup; their tools are injected into each lane.
_mcp_adapters: list[Any] = []
_mcp_tools: list[Any] = []
_last_mcp_signature: str | None = None
_mcp_refresh_lock = asyncio.Lock()


def _workspace_root() -> Path:
    """Resolve the .proxi workspace root."""
    env = os.environ.get("PROXI_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".proxi"


async def _refresh_mcp_tools() -> None:
    """Reload MCP tools when the enabled-MCP set has changed."""
    global _mcp_adapters, _mcp_tools, _last_mcp_signature

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
            json.dumps(sig_payload, sort_keys=True, separators=(",", ":")).encode()
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

        try:
            from proxi.tools.registry import ToolRegistry as _TR

            tmp_registry = _TR()
            _mcp_adapters[:] = await asyncio.wait_for(
                auto_load_mcp_servers(tmp_registry), timeout=30.0
            )
            _mcp_tools[:] = list(tmp_registry._tools.values())
            logger.info("mcp_refreshed", adapters=len(_mcp_adapters), tools=len(_mcp_tools))
        except Exception as exc:
            logger.warning("mcp_refresh_error", error=str(exc))

        # Existing lanes keep the same AgentLoop + ToolRegistry; refresh replaces
        # global tool objects and closes old MCP stdio clients — push the new tools
        # into every active loop so toggles take effect without restarting the gateway.
        if lane_manager is not None:
            lane_manager.sync_mcp_tools_to_loops(_mcp_tools)


def _create_agent_loop(workspace_config: WorkspaceConfig) -> AgentLoop:
    """Factory called by LaneManager to create an AgentLoop per session.

    Each lane gets its own tool registry so workspace-scoped tools
    (plan, todos, soul) resolve to the correct session paths.
    MCP tools loaded at gateway startup are shared across all lanes.
    """
    provider = os.environ.get("PROXI_PROVIDER", "openai").lower()
    llm_client = create_llm_client(provider=provider)

    tool_registry = setup_tools()
    tool_registry.register_raw_spec(get_show_collaborative_form_spec())
    tool_registry.register(ManagePlanTool(workspace_config))
    tool_registry.register(ManageTodosTool(workspace_config))
    tool_registry.register(ReadSoulTool(workspace_config))

    for mcp_tool in _mcp_tools:
        tool_registry.register(mcp_tool)

    no_sub_agents = os.environ.get("PROXI_NO_SUB_AGENTS", "").lower() in (
        "1", "true", "yes",
    )
    sub_agent_manager = None if no_sub_agents else setup_sub_agents(llm_client)

    max_turns = int(os.environ.get("PROXI_MAX_TURNS", "20"))
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

    workspace_root = _workspace_root()
    WorkspaceManager(root=workspace_root).ensure_global_system_prompt()

    config = GatewayConfig.load(workspace_root)
    router = EventRouter(config)

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
                logger.info("http_lane_prewarmed", source=source_id, session=session_id)
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
        chat_id = str(cq["message"]["chat"]["id"])
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
        raise HTTPException(status_code=403, detail="Verification token mismatch")
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
    raw = await request.json()

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


class SwitchAgentRequest(BaseModel):
    agent_id: str


@app.post("/v1/sessions/switch")
async def switch_agent_endpoint(body: SwitchAgentRequest) -> dict[str, Any]:
    """Switch the TUI to a different agent.

    Returns the new session_id the TUI should reconnect to.
    """
    agent = config.agents.get(body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {body.agent_id}")
    new_session_id = f"{agent.agent_id}/{agent.default_session}"
    lane_manager._get_or_create(new_session_id)
    return {"session_id": new_session_id, "agent_id": agent.agent_id}


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
