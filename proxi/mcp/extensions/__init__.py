"""MCP Extensions - extensible framework for various service integrations.

This module provides a framework for integrating different services via MCP (Model Context Protocol).
Each service integration (Gmail, Slack, Jira, etc.) is implemented as a separate module that can be
loaded dynamically based on configuration.

Supported Extensions:
- gmail: Gmail integration with search, send, summarize capabilities

For adding new extensions, see README.md and base.py documentation.
"""

# Import extension registry for external use
from proxi.mcp.extensions.base import (
    BaseMCPExtension,
    ExtensionRegistry,
    get_registry,
    register_extension,
)

__all__ = [
    "BaseMCPExtension",
    "ExtensionRegistry",
    "get_registry",
    "register_extension",
    "gmail",
]

