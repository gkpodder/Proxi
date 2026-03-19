"""MCP (Model Context Protocol) client implementation."""

import asyncio
import json
import os
from typing import Any

from proxi.observability.logging import get_logger
from proxi.observability.perf import elapsed_ms, emit_perf, now_ns

logger = get_logger(__name__)


class MCPClientError(RuntimeError):
    """Base MCP client exception."""


class MCPTimeoutError(MCPClientError):
    """Timeout waiting for MCP response."""


class MCPCircuitOpenError(MCPClientError):
    """Raised when MCP circuit breaker is open."""


class MCPClient:
    """Client for connecting to MCP servers using JSON-RPC 2.0 over stdio."""

    def __init__(self, server_command: list[str]):
        """
        Initialize MCP client.

        Args:
            server_command: Command to start the MCP server (e.g., ["python", "server.py"])
        """
        self.server_command = server_command
        self.process: asyncio.subprocess.Process | None = None
        self.request_id = 0
        self.initialized = False
        self.pending_requests: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.logger = logger
        self._read_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._max_inflight = max(1, int(os.getenv("PROXI_MCP_MAX_INFLIGHT", "16")))
        self._request_semaphore = asyncio.Semaphore(self._max_inflight)
        self._max_retries = max(0, int(os.getenv("PROXI_MCP_MAX_RETRIES", "1")))
        self._retry_backoff_ms = max(1, int(os.getenv("PROXI_MCP_RETRY_BACKOFF_MS", "200")))
        self._timeout_threshold = max(1, int(os.getenv("PROXI_MCP_CIRCUIT_THRESHOLD", "4")))
        self._circuit_cooldown_s = max(1, int(os.getenv("PROXI_MCP_CIRCUIT_COOLDOWN_S", "10")))
        self._consecutive_timeouts = 0
        self._circuit_open_until = 0.0

    async def _get_next_request_id(self) -> int:
        """Get the next request ID."""
        self.request_id += 1
        return self.request_id

    async def _read_loop(self) -> None:
        """Background task to read responses from MCP server."""
        if not self.process or not self.process.stdout:
            return

        while True:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break

                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    response = json.loads(line_str)
                    response_id = response.get("id")
                    if response_id is not None and response_id in self.pending_requests:
                        future = self.pending_requests.pop(response_id)
                        if "error" in response:
                            error = response["error"]
                            future.set_exception(
                                RuntimeError(
                                    f"MCP error: {error.get('message', 'Unknown error')} (code: {error.get('code')})"
                                )
                            )
                        else:
                            future.set_result(response.get("result", {}))
                except json.JSONDecodeError:
                    # Skip non-JSON lines (like stderr output or server logs)
                    self.logger.debug("mcp_non_json_line", line=line_str[:100])
                    continue

            except Exception as e:
                self.logger.error("mcp_read_error", error=str(e))
                break

        self._fail_pending_requests("MCP server closed connection")

    async def _read_stderr(self) -> None:
        """Background task to read stderr from MCP server."""
        if not self.process or not self.process.stderr:
            return

        while True:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                line_str = line.decode(errors="replace").strip()
                if line_str:
                    self.logger.warning("mcp_server_stderr", line=line_str[:500])
            except Exception as e:
                self.logger.error("mcp_stderr_error", error=str(e))
                break

    def _fail_pending_requests(self, message: str) -> None:
        """Fail all pending requests with a runtime error."""
        for request_id, future in list(self.pending_requests.items()):
            if not future.done():
                future.set_exception(RuntimeError(message))
            self.pending_requests.pop(request_id, None)

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if not self.process or not self.process.stdin:
            raise MCPClientError("MCP client not connected")

        now = asyncio.get_running_loop().time()
        if now < self._circuit_open_until:
            emit_perf(
                "perf_mcp_request",
                method=method,
                status="circuit_open",
                elapsed_ms=0.0,
                pending_depth=len(self.pending_requests),
            )
            raise MCPCircuitOpenError(f"MCP circuit open for method={method}")

        can_retry = method != "tools/call" or os.getenv("PROXI_MCP_RETRY_TOOL_CALLS", "0") in {"1", "true", "yes"}
        attempts = self._max_retries + 1 if can_retry else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await self._send_request_once(method, params=params, timeout=timeout)
            except MCPTimeoutError as e:
                last_error = e
                self._consecutive_timeouts += 1
                if self._consecutive_timeouts >= self._timeout_threshold:
                    self._circuit_open_until = asyncio.get_running_loop().time() + self._circuit_cooldown_s
                    emit_perf(
                        "perf_mcp_circuit_opened",
                        method=method,
                        threshold=self._timeout_threshold,
                        cooldown_s=self._circuit_cooldown_s,
                    )
                if attempt >= attempts:
                    raise
                await asyncio.sleep((self._retry_backoff_ms * attempt) / 1000.0)
                emit_perf("perf_mcp_retry", method=method, attempt=attempt)
            except Exception as e:
                last_error = e
                if attempt >= attempts:
                    raise
                await asyncio.sleep((self._retry_backoff_ms * attempt) / 1000.0)
                emit_perf("perf_mcp_retry", method=method, attempt=attempt)

        if last_error is not None:
            raise last_error
        raise MCPClientError("MCP request failed unexpectedly")

    async def _send_request_once(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send one JSON-RPC request attempt and wait for response."""
        if not self.process or not self.process.stdin:
            raise MCPClientError("MCP client not connected")

        request_id = await self._get_next_request_id()
        request_start_ns = now_ns()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Create future for response
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self.pending_requests[request_id] = future
        emit_perf(
            "perf_mcp_pending_depth",
            method=method,
            depth=len(self.pending_requests),
        )

        # Send request
        request_json = json.dumps(request) + "\n"
        async with self._request_semaphore:
            self.process.stdin.write(request_json.encode())
            await self.process.stdin.drain()

        self.logger.debug("mcp_request_sent", method=method, id=request_id)

        # Wait for response with timeout
        try:
            wait_timeout = 30.0 if timeout is None else timeout
            result = await asyncio.wait_for(future, timeout=wait_timeout)
            emit_perf(
                "perf_mcp_request",
                method=method,
                status="ok",
                elapsed_ms=round(elapsed_ms(request_start_ns), 3),
                pending_depth=len(self.pending_requests),
            )
            self._consecutive_timeouts = 0
            return result
        except asyncio.TimeoutError:
            self.pending_requests.pop(request_id, None)
            emit_perf(
                "perf_mcp_request",
                method=method,
                status="timeout",
                elapsed_ms=round(elapsed_ms(request_start_ns), 3),
                pending_depth=len(self.pending_requests),
            )
            raise MCPTimeoutError(f"MCP request timeout: {method}")

    async def initialize(self) -> dict[str, Any]:
        """Initialize connection to MCP server."""
        if self.initialized:
            return {"protocolVersion": "2024-11-05", "capabilities": {}}

        self.logger.info("mcp_client_initializing",
                         command=" ".join(self.server_command))

        # Start the MCP server process
        self.process = await asyncio.create_subprocess_exec(
            *self.server_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError("Failed to create MCP server process")

        # Start background read loop
        self._read_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._read_stderr())

        # Send initialize request
        init_timeout = float(os.getenv("PROXI_MCP_INIT_TIMEOUT", "60"))
        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "proxi",
                    "version": "0.1.0",
                },
            },
            timeout=init_timeout,
        )

        # Send initialized notification
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        notification_json = json.dumps(initialized_notification) + "\n"
        self.process.stdin.write(notification_json.encode())
        await self.process.stdin.drain()

        self.initialized = True
        self.logger.info("mcp_client_initialized",
                         protocol_version=result.get("protocolVersion"))

        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from MCP server."""
        self.logger.debug("mcp_list_tools")
        result = await self._send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        self.logger.debug("mcp_call_tool", tool=name)
        result = await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        return result

    async def list_resources(self) -> list[dict[str, Any]]:
        """List available resources from MCP server."""
        self.logger.debug("mcp_list_resources")
        result = await self._send_request("resources/list")
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource from MCP server."""
        self.logger.debug("mcp_read_resource", uri=uri)
        result = await self._send_request(
            "resources/read",
            {"uri": uri},
        )
        return result

    async def close(self) -> None:
        """Close the MCP connection."""
        # Cancel read task
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

        # Close stdin to signal server to shutdown
        if self.process and self.process.stdin:
            try:
                self.process.stdin.close()
                await self.process.stdin.wait_closed()
            except Exception:
                pass

        # Wait for process to terminate
        if self.process:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            except Exception:
                pass

        # Cancel any pending requests
        for future in self.pending_requests.values():
            if not future.done():
                future.cancel()
        self.pending_requests.clear()

        self.process = None
        self._read_task = None
        self._stderr_task = None
        self.initialized = False
        self.logger.info("mcp_client_closed")
