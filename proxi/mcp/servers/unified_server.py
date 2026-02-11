"""Unified MCP server for multiple integrations (Gmail, Notion, Calendar, etc.)."""

import asyncio
import json
import sys
from typing import Any

from proxi.mcp.servers.integrations.base import BaseIntegration
from proxi.mcp.servers.integrations.gmail import GmailIntegration


class UnifiedMCPServer:
    """MCP server that hosts multiple integrations."""

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize unified MCP server.

        Args:
            config: Configuration dictionary for integrations
        """
        self.config = config or {}
        self.integrations: dict[str, BaseIntegration] = {}
        self.initialized = False

    def register_integration(self, integration: BaseIntegration) -> None:
        """Register an integration with the server."""
        name = integration.get_name()
        self.integrations[name] = integration

    async def initialize(self) -> None:
        """Initialize all registered integrations."""
        if self.initialized:
            return

        # Auto-register available integrations based on config
        enabled_integrations = self.config.get("enabled_integrations", [])

        if "gmail" in enabled_integrations:
            gmail_config = self.config.get("gmail", {})
            gmail = GmailIntegration(gmail_config)
            self.register_integration(gmail)

        # Note: Integrations are registered but NOT initialized yet
        # They will be initialized lazily on first use to avoid blocking
        sys.stderr.write(f"Registered integrations: {list(self.integrations.keys())}\n")
        sys.stderr.flush()

        self.initialized = True

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all tools from all enabled integrations."""
        tools = []
        for integration in self.integrations.values():
            if integration.enabled:
                tools.extend(integration.get_tools())
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool by routing to the appropriate integration."""
        # Determine which integration owns this tool
        for integration in self.integrations.values():
            if not integration.enabled:
                continue
                
            tool_names = [tool["name"] for tool in integration.get_tools()]
            if name in tool_names:
                # Lazy initialization: initialize the integration on first use
                if not hasattr(integration, '_initialized') or not integration._initialized:
                    try:
                        sys.stderr.write(f"Initializing {integration.get_name()} on first use...\n")
                        sys.stderr.flush()
                        await integration.initialize()
                        integration._initialized = True
                        sys.stderr.write(f"Successfully initialized {integration.get_name()}\n")
                        sys.stderr.flush()
                    except Exception as e:
                        sys.stderr.write(f"Failed to initialize {integration.get_name()}: {str(e)}\n")
                        sys.stderr.flush()
                        integration.enabled = False
                        return {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Failed to initialize {integration.get_name()}: {str(e)}\n\nPlease check your credentials and try again.",
                                }
                            ],
                            "isError": True,
                        }
                
                return await integration.call_tool(name, arguments)

        return {
            "content": [{"type": "text", "text": f"Tool not found: {name}"}],
            "isError": True,
        }

    async def cleanup(self) -> None:
        """Cleanup all integrations."""
        for integration in self.integrations.values():
            try:
                await integration.cleanup()
            except Exception as e:
                sys.stderr.write(f"Error cleaning up {integration.get_name()}: {e}\n")
                sys.stderr.flush()


class MCPProtocolHandler:
    """Handle MCP protocol communication via stdio."""

    def __init__(self, server: UnifiedMCPServer):
        """Initialize protocol handler."""
        self.server = server
        self.request_id = 0

    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request."""
        await self.server.initialize()
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": "proxi-unified-mcp-server",
                "version": "0.1.0",
            },
        }

    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request."""
        tools = self.server.get_all_tools()
        return {"tools": tools}

    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        name = params.get("name")
        arguments = params.get("arguments", {})
        return await self.server.call_tool(name, arguments)

    async def process_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process a JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        # Handle notifications (no response needed)
        if method == "notifications/initialized":
            return None

        # Handle requests
        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        except Exception as e:
            sys.stderr.write(f"Error processing request: {str(e)}\n")
            sys.stderr.flush()
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}",
                },
            }

    async def run(self) -> None:
        """Run the MCP server protocol loop."""
        sys.stderr.write("Unified MCP Server starting...\n")
        sys.stderr.flush()

        while True:
            try:
                # Read a line from stdin
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )

                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                # Parse JSON-RPC request
                request = json.loads(line)

                # Process request
                response = await self.process_request(request)

                # Send response if not a notification
                if response:
                    response_json = json.dumps(response) + "\n"
                    sys.stdout.write(response_json)
                    sys.stdout.flush()

            except json.JSONDecodeError as e:
                sys.stderr.write(f"Invalid JSON: {e}\n")
                sys.stderr.flush()
            except Exception as e:
                sys.stderr.write(f"Error in main loop: {e}\n")
                sys.stderr.flush()

        # Cleanup
        await self.server.cleanup()


async def main() -> None:
    """Main entry point for unified MCP server."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Unified MCP Server for multiple integrations"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file (JSON)",
    )
    parser.add_argument(
        "--enable-gmail",
        action="store_true",
        help="Enable Gmail integration",
    )

    args = parser.parse_args()

    # Load configuration
    config: dict[str, Any] = {"enabled_integrations": []}

    if args.config:
        try:
            with open(args.config, "r") as f:
                config = json.load(f)
        except Exception as e:
            sys.stderr.write(f"Failed to load config: {e}\n")
            sys.stderr.flush()

    # Override with CLI arguments
    if args.enable_gmail:
        if "gmail" not in config.get("enabled_integrations", []):
            config.setdefault("enabled_integrations", []).append("gmail")

    # Create and run server
    server = UnifiedMCPServer(config)
    handler = MCPProtocolHandler(server)
    await handler.run()


if __name__ == "__main__":
    asyncio.run(main())
