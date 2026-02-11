"""Base integration class for MCP server integrations."""

from abc import ABC, abstractmethod
from typing import Any


class BaseIntegration(ABC):
    """Base class for MCP server integrations."""

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize the integration.

        Args:
            config: Configuration dictionary for the integration
        """
        self.config = config or {}
        self.enabled = True

    @abstractmethod
    def get_name(self) -> str:
        """Get the integration name."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the integration (setup auth, connections, etc.)."""
        pass

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """
        Get the list of tools provided by this integration.

        Returns:
            List of tool specifications in MCP format
        """
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool provided by this integration.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result in MCP format
        """
        pass

    async def cleanup(self) -> None:
        """Cleanup resources. Override if needed."""
        pass
