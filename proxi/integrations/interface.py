"""Integration interface — describes a single external service integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Integration:
    """Describes an external service integration.

    An integration groups one or more tools (CLI-backed or MCP-backed) that
    together provide access to a single external service (e.g. Gmail, Spotify).

    Attributes:
        name: Unique integration identifier (e.g. "gmail", "spotify").
        description: Human-readable description shown in settings UIs.
        type: Backend type — "cli" for CLI-script-backed tools, "mcp" for
              Model Context Protocol server-backed tools.
        defer_loading: When True, tools are hidden from the LLM by default
                       and discovered on-demand via search_tools / call_tool.
        always_load: Tool names that are exposed to the LLM immediately even
                     when defer_loading is True.
    """

    name: str
    description: str
    type: Literal["cli", "mcp"]
    defer_loading: bool = True
    always_load: list[str] = field(default_factory=list)
