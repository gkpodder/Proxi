"""FastAPI server for the proxi frontend."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Load environment variables from .env file if it exists
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from proxi.agents.registry import SubAgentManager, SubAgentRegistry
from proxi.agents.summarizer import SummarizerAgent
from proxi.core.loop import AgentLoop
from proxi.llm.anthropic import AnthropicClient
from proxi.llm.openai import OpenAIClient
from proxi.mcp.adapters import MCPAdapter
from proxi.mcp.client import MCPClient
from proxi.mcp.multiplexer import MCPMultiplexer
from proxi.observability.logging import setup_logging, get_logger
from proxi.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool
from proxi.tools.registry import ToolRegistry
from proxi.tools.shell import ExecuteCommandTool

logger = get_logger(__name__)

# Setup logging at module load time
setup_logging(level="INFO")

# Ensure subprocess support for asyncio on Windows (needed for MCP servers)
# This MUST be done at module import time, before any event loop is created
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

_tool_registry: ToolRegistry | None = None
_mcp_adapter: MCPAdapter | MCPMultiplexer | None = None
_sub_agent_manager: SubAgentManager | None = None
_init_lock: asyncio.Lock | None = None
_run_lock: asyncio.Lock | None = None


def _get_init_lock() -> asyncio.Lock:
    """Get or create the initialization lock."""
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


def _get_run_lock() -> asyncio.Lock:
    """Get or create the run lock."""
    global _run_lock
    if _run_lock is None:
        _run_lock = asyncio.Lock()
    return _run_lock


async def _ensure_initialized() -> None:
    global _tool_registry, _mcp_adapter, _sub_agent_manager
    async with _get_init_lock():
        if _tool_registry is None:
            _tool_registry, _mcp_adapter = await setup_mcp_servers()
            _sub_agent_manager = await setup_agents()


def _count_mcp_tools(registry: ToolRegistry | None) -> int:
    if not registry:
        return 0
    return sum(1 for t in registry.list_tools() if t.name.startswith("mcp_"))


def _clean_cli_output(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith((
            "[",
            "INFO:",
            "WARNING:",
            "ERROR:",
            "DEBUG:",
            "HTTP Request:",
        )):
            continue
        if stripped.startswith((
            "================================================================================",
            "--------------------------------------------------------------------------------",
            "AGENT COMPLETED",
            "Status:",
            "Turns:",
            "Duration:",
            "Total tokens:",
        )):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCPs once at startup and reuse across requests."""
    global _tool_registry, _mcp_adapter, _sub_agent_manager
    await _ensure_initialized()
    try:
        yield
    finally:
        if _mcp_adapter:
            try:
                await _mcp_adapter.close()
            except Exception as e:
                logger.error("mcp_close_error", error=str(e))


app = FastAPI(title="Proxi Frontend API", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProxiRequest(BaseModel):
    """Request model for proxi execution."""
    prompt: str
    provider: str = "openai"


def create_llm_client(provider: str = "openai") -> OpenAIClient | AnthropicClient:
    """Create an LLM client based on provider."""
    if provider.lower() == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        return AnthropicClient(api_key=api_key)
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        return OpenAIClient(api_key=api_key)


def setup_tools(working_directory: Path | None = None) -> ToolRegistry:
    """Set up the tool registry with default tools."""
    registry = ToolRegistry()

    # Filesystem tools
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())

    # Shell tool
    registry.register(ExecuteCommandTool(working_directory=working_directory))

    return registry


async def setup_mcp_servers() -> tuple[ToolRegistry, MCPAdapter | MCPMultiplexer | None]:
    """Set up MCP servers (Gmail, Notion) if credentials are configured."""
    # Reload .env in case the process started before it was available
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)

    tool_registry = setup_tools()
    mcp_adapter = None
    mcp_servers_to_enable = []

    # Auto-enable Notion MCP if credentials are configured
    notion_api_key = os.getenv("NOTION_API_KEY")
    logger.info("checking_notion_credentials", has_key=bool(notion_api_key))
    if notion_api_key:
        notion_server_path = Path(__file__).parent.parent / "mcp" / "extensions" / "notion.py"
        logger.info("notion_server_path", path=str(notion_server_path), exists=notion_server_path.exists())
        if notion_server_path.exists():
            mcp_servers_to_enable.append([sys.executable, str(notion_server_path)])
            logger.info("notion_mcp_enabled", path=str(notion_server_path))
        else:
            logger.warning("notion_server_not_found", path=str(notion_server_path))

    # Auto-enable Gmail MCP if credentials are configured
    gmail_client_id = os.getenv("GMAIL_CLIENT_ID")
    gmail_token = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    token_path = Path(gmail_token)
    if not token_path.is_absolute():
        token_path = Path(__file__).parent.parent.parent / token_path
    logger.info(
        "checking_gmail_credentials",
        has_client_id=bool(gmail_client_id),
        token_path=str(token_path),
        token_exists=token_path.exists(),
    )
    if gmail_client_id or token_path.exists():
        gmail_server_path = Path(__file__).parent.parent / "mcp" / "extensions" / "gmail.py"
        logger.info("gmail_server_path", path=str(gmail_server_path), exists=gmail_server_path.exists())
        if gmail_server_path.exists():
            mcp_servers_to_enable.append([sys.executable, str(gmail_server_path)])
            logger.info("gmail_mcp_enabled", path=str(gmail_server_path))
        else:
            logger.warning("gmail_server_not_found", path=str(gmail_server_path))

    logger.info("mcp_servers_to_enable", count=len(mcp_servers_to_enable), servers=mcp_servers_to_enable)

    # NOTE: MCP initialization via asyncio.create_subprocess_exec fails on Windows with Python 3.14+
    # The CLI fallback handles this perfectly via subprocess.Popen directly,
    # so we skip MCP initialization here and rely on the fallback for all MCP operations.
    logger.info("mcp_initialization_disabled", reason="Using CLI fallback for reliability")
    
    return tool_registry, None


async def setup_agents() -> SubAgentManager:
    """Set up the sub-agent manager."""
    registry = SubAgentRegistry()
    manager = SubAgentManager(registry)
    return manager


@app.websocket("/ws/execute")
async def websocket_execute(websocket: WebSocket):
    """WebSocket endpoint for executing proxi with streaming status."""
    logger.info("websocket_connection_attempt", client=websocket.client)
    await websocket.accept()
    logger.info("websocket_accepted")
    
    try:
        # Receive the initial request
        logger.info("waiting_for_message")
        data = await websocket.receive_text()
        logger.info("received_message", data_length=len(data))
        request = ProxiRequest(**json.loads(data))
        logger.info("parsed_request", prompt_length=len(request.prompt), provider=request.provider)
        
        # Send acknowledgement
        await websocket.send_json({
            "type": "started",
            "message": f"Starting execution with prompt: {request.prompt[:50]}..."
        })
        logger.info("sent_acknowledgement")
        
        # Send initialization status
        await websocket.send_json({
            "type": "status",
            "status": "initializing",
            "message": "Setting up MCPs..."
        })
        
        try:
            # Ensure shared components are initialized
            await _ensure_initialized()

            mcp_tool_count = _count_mcp_tools(_tool_registry)
            await websocket.send_json({
                "type": "status",
                "status": "mcp_tools",
                "message": f"MCP tools available: {mcp_tool_count}"
            })

            # Fallback to CLI if MCP tools failed to load
            if mcp_tool_count == 0:
                await websocket.send_json({
                    "type": "status",
                    "status": "fallback",
                    "message": "MCP tools unavailable; using CLI fallback without MCP"
                })
                import subprocess
                import shutil
                import re

                project_root = Path(__file__).parent.parent.parent
                uv_path = shutil.which("uv")

                # Don't use MCP flags since MCP servers aren't loaded
                if uv_path:
                    cmd = [
                        uv_path,
                        "run",
                        "proxi",
                        request.prompt,
                    ]
                else:
                    cmd = [
                        sys.executable,
                        "-m",
                        "proxi.cli.main",
                        request.prompt,
                    ]

                logger.info("fallback_to_cli", cmd=cmd)

                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            subprocess.run,
                            cmd,
                            capture_output=True,
                            text=True,
                            cwd=project_root,
                            env=os.environ.copy(),
                        ),
                        timeout=120  # 2 minute timeout
                    )
                except asyncio.TimeoutError:
                    await websocket.send_json({
                        "type": "error",
                        "error": "CLI command timed out after 2 minutes"
                    })
                    logger.error("cli_timeout", cmd=cmd)
                    return

                output = result.stdout or ""
                error_output = result.stderr or ""
                
                logger.info("cli_completed", 
                           return_code=result.returncode,
                           stdout_length=len(output),
                           stderr_length=len(error_output))
                
                if result.returncode != 0:
                    await websocket.send_json({
                        "type": "error",
                        "error": f"CLI failed: {error_output or output or 'Unknown error'}"
                    })
                    logger.error("cli_failed", return_code=result.returncode, stderr=error_output)
                    return
                
                final_response = None
                parsed_tokens = None
                parsed_turns = None

                if "Final Response:" in output:
                    final_response = output.split("Final Response:")[-1].strip()
                    if "AGENT COMPLETED" in final_response:
                        final_response = final_response.split("AGENT COMPLETED")[0].strip()
                elif "AGENT COMPLETED" in output:
                    parts = output.split("================================================================================")
                    if len(parts) >= 3:
                        final_response = parts[2].strip()
                        if final_response.startswith("AGENT COMPLETED"):
                            final_response = final_response.split("Final Response:", 1)[-1].strip() if "Final Response:" in final_response else final_response

                tokens_match = re.search(r"Total tokens:\s*(\d+)", output)
                if tokens_match:
                    parsed_tokens = int(tokens_match.group(1))
                turns_match = re.search(r"Turns:\s*(\d+)\s*/\s*(\d+)", output)
                if turns_match:
                    parsed_turns = int(turns_match.group(1))

                cleaned_final = _clean_cli_output(final_response or "")
                cleaned_output = _clean_cli_output(output)
                cleaned_error = _clean_cli_output(error_output)

                await websocket.send_json({
                    "type": "status",
                    "status": "completed",
                    "message": "Execution finished"
                })

                await websocket.send_json({
                    "type": "completed",
                    "result": cleaned_final or cleaned_output or cleaned_error or "No result",
                    "tokens_used": parsed_tokens,
                    "turns": parsed_turns,
                })
                return

            # Run the agent loop (serialize to avoid concurrent access to shared MCPs)
            async with _get_run_lock():
                llm_client = create_llm_client(request.provider)
                agent_loop = AgentLoop(
                    llm_client=llm_client,
                    tool_registry=_tool_registry,  # type: ignore[arg-type]
                    sub_agent_manager=_sub_agent_manager,
                    max_turns=50,
                    enable_reflection=True,
                )

                await websocket.send_json({
                    "type": "status",
                    "status": "running",
                    "message": "Agent running"
                })

                final_state = await agent_loop.run(request.prompt)

                # Extract final assistant message
                final_message = None
                for msg in reversed(final_state.history):
                    if msg.role == "assistant" and msg.content:
                        final_message = msg.content
                        break

            await websocket.send_json({
                "type": "status",
                "status": "completed",
                "message": "Execution finished"
            })

            await websocket.send_json({
                "type": "completed",
                "result": final_message or "No result",
                "tokens_used": final_state.total_tokens,
                "turns": final_state.current_turn,
            })
            
        except asyncio.TimeoutError:
            logger.error("execution_timeout")
            await websocket.send_json({
                "type": "error",
                "error": "Execution timed out (5 minute limit)"
            })
        except Exception as e:
            logger.error("execution_error", error=str(e), exc_info=True)
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
            
    except WebSocketDisconnect:
        logger.info("websocket_disconnected")
    except Exception as e:
        logger.error("websocket_error", error=str(e), exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
        except Exception:
            pass


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/debug/mcps")
async def debug_mcps():
    """Debug endpoint to check MCP status."""
    await _ensure_initialized()
    registry = _tool_registry
    if not registry:
        return {
            "status": "no registry",
            "gmail_client_id": bool(os.getenv("GMAIL_CLIENT_ID")),
            "notion_api_key": bool(os.getenv("NOTION_API_KEY"))
        }
    tools = registry.list_tools()
    tool_names = [t.name for t in tools]
    return {
        "status": "loaded",
        "tool_count": len(tools),
        "mcp_tool_count": _count_mcp_tools(registry),
        "tools": tool_names,
    }


# Try to serve static files if frontend is built
frontend_path = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
