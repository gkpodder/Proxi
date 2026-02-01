"""MCP (Model Context Protocol) client implementation."""

import asyncio
import json
import subprocess
from typing import Any

from proxi.observability.logging import get_logger

logger = get_logger(__name__)


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

    async def _send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if not self.process or not self.process.stdin:
            raise RuntimeError("MCP client not connected")

        request_id = await self._get_next_request_id()
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

        # Send request
        request_json = json.dumps(request) + "\n"
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()

        self.logger.debug("mcp_request_sent", method=method, id=request_id)

        # Wait for response with timeout
        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            self.pending_requests.pop(request_id, None)
            raise RuntimeError(f"MCP request timeout: {method}")

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

        # Send initialize request
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
        self.initialized = False
        self.logger.info("mcp_client_closed")
