"""Template for creating new MCP integrations.

Copy this file to create a new integration (e.g., notion.py, calendar.py, slack.py).
"""

from typing import Any

from proxi.mcp.servers.integrations.base import BaseIntegration


class TemplateIntegration(BaseIntegration):
    """Template integration - replace with your integration name."""

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize the integration.

        Args:
            config: Configuration dictionary with credentials, paths, etc.
        """
        super().__init__(config)
        # Add your initialization here
        self.client = None
        self.credentials = None

    def get_name(self) -> str:
        """
        Get the integration name.

        Returns:
            A unique lowercase name for this integration (e.g., 'notion', 'calendar')
        """
        return "template"  # Change this!

    async def initialize(self) -> None:
        """
        Initialize the integration.

        This method should:
        1. Load credentials/API keys from config
        2. Authenticate with the service
        3. Set up any necessary clients or connections
        4. Raise RuntimeError if initialization fails

        Raises:
            RuntimeError: If initialization fails
        """
        # Example: Load API key from config
        api_key = self.config.get("api_key")
        if not api_key:
            raise RuntimeError("Template API key not found in configuration")

        # Example: Initialize client
        # self.client = YourServiceClient(api_key=api_key)

        # Mark as enabled if successful
        self.enabled = True

    def get_tools(self) -> list[dict[str, Any]]:
        """
        Get the list of tools provided by this integration.

        Each tool must have:
        - name: Unique tool name (use integration_action format)
        - description: What the tool does
        - inputSchema: JSON schema for tool parameters

        Returns:
            List of tool specifications in MCP format
        """
        return [
            {
                "name": "template_example_action",
                "description": "Example tool - describe what it does",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "param1": {
                            "type": "string",
                            "description": "Description of parameter 1",
                        },
                        "param2": {
                            "type": "integer",
                            "description": "Description of parameter 2",
                            "default": 10,
                        },
                    },
                    "required": ["param1"],  # List required parameters
                },
            },
            # Add more tools here
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool provided by this integration.

        Args:
            name: Tool name (from get_tools)
            arguments: Tool arguments (validated against inputSchema)

        Returns:
            Tool result in MCP format with 'content' field:
            {
                "content": [
                    {"type": "text", "text": "Result text here"}
                ],
                "isError": False  # Optional, set to True on error
            }
        """
        if not self.enabled or not self.client:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Service not initialized. Check configuration.",
                    }
                ],
                "isError": True,
            }

        try:
            if name == "template_example_action":
                return await self._example_action(
                    param1=arguments.get("param1"),
                    param2=arguments.get("param2", 10),
                )
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True,
                }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    async def _example_action(self, param1: str, param2: int) -> dict[str, Any]:
        """
        Example action implementation.

        Args:
            param1: First parameter
            param2: Second parameter

        Returns:
            MCP-formatted result
        """
        # Implement your action here
        # Example: result = self.client.do_something(param1, param2)

        result_text = f"Example action called with {param1} and {param2}"

        return {
            "content": [{"type": "text", "text": result_text}],
        }

    async def cleanup(self) -> None:
        """
        Cleanup resources when shutting down.

        Override this if you need to close connections, save state, etc.
        """
        if self.client:
            # Example: await self.client.close()
            pass


# ============================================================================
# Integration Registration
# ============================================================================
# To register your integration in the unified server:
#
# 1. Import your integration in unified_server.py:
#    from proxi.mcp.servers.integrations.your_integration import YourIntegration
#
# 2. Add registration in UnifiedMCPServer.initialize():
#    if "your_integration" in enabled_integrations:
#        your_config = self.config.get("your_integration", {})
#        integration = YourIntegration(your_config)
#        self.register_integration(integration)
#
# 3. Add to config.json.example:
#    "your_integration": {
#      "enabled": false,
#      "api_key": "",
#      "other_config": ""
#    }
#
# 4. Document in README.md with setup instructions
# ============================================================================
