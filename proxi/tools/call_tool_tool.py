"""call_tool — discover and execute deferred tools in one step.

The LLM calls this with the tool name it wants (from the AVAILABLE ON DEMAND
stubs in the system prompt) and the args it believes are correct.

Execution paths:
  1. Exact name match in deferred registry → execute immediately.
  2. Name not found → BM25 search; if relevant matches exist, return their
     schemas so the LLM can retry with the correct name and args.
  3. No relevant matches → clear "no such tool" message.

Deferred tools are never promoted to the live tools array so the
prompt-cache prefix stays stable for the entire session.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from proxi.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from proxi.tools.registry import ToolRegistry

# Fraction of the best BM25 score a candidate must reach to be shown as a
# suggestion.  Filters out low-relevance "tail" matches from BM25.
_RELEVANCE_THRESHOLD = 0.4


class CallToolTool(BaseTool):
    """Discover and execute a deferred tool by name.

    Pass the tool name from the AVAILABLE ON DEMAND list in the system prompt
    and the args you believe it requires.  If the name is not found, relevant
    alternatives are returned — retry with the correct name.
    """

    def __init__(self, registry: "ToolRegistry") -> None:
        super().__init__(
            name="call_tool",
            description=(
                "Execute a tool from the AVAILABLE ON DEMAND list. "
                "Pass the exact tool_name and the args it requires — include every "
                "required key from the schema (e.g. weather tools need `location` in "
                "`args` or the CLI exits with a usage error). "
                "If the tool is not found, relevant alternatives are returned — "
                "retry with the correct name. "
                "Do NOT call live tools to gather info before calling this. "
                "PARALLEL: when multiple independent calls are needed (e.g. weather for "
                "several cities, reading several notes), issue ALL call_tool invocations "
                "in a single response as multiple tool_calls — never one at a time."
            ),
            parameters_schema={
                "type": "object",
                "required": ["tool_name", "args"],
                "additionalProperties": False,
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the tool to execute (from AVAILABLE ON DEMAND).",
                    },
                    "args": {
                        "type": "object",
                        "description": "Arguments for the tool.",
                    },
                },
            },
            parallel_safe=False,
        )
        self._registry = registry

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        tool_name = (arguments.get("tool_name") or "").strip()
        args = arguments.get("args") or {}

        if not tool_name:
            return ToolResult(success=False, output="", error="tool_name is required")
        if not isinstance(args, dict):
            return ToolResult(success=False, output="", error="args must be an object")

        # --- Path 1: exact match in deferred tier → execute ---
        if tool_name in self._registry._deferred_tools:
            return await self._registry.execute_deferred(tool_name, args)

        # --- Path 1b: tool exists but in the live tier → give specific guidance ---
        if tool_name in self._registry._tools:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"'{tool_name}' is already in your live tools list — "
                    "call it directly without call_tool."
                ),
            )

        # --- Path 2: not found → search for suggestions ---
        if not self._registry.has_deferred_tools():
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{tool_name}' not found. No additional tools are available.",
            )

        scored = self._registry.suggest_deferred(tool_name, top_k=3)

        if not scored:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Tool '{tool_name}' not found and no similar tools matched. "
                    "Check the AVAILABLE ON DEMAND list in the system prompt."
                ),
            )

        best_score = scored[0][0]
        relevant = [(s, spec) for s, spec in scored if s >= best_score * _RELEVANCE_THRESHOLD]

        if not relevant:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Tool '{tool_name}' not found. "
                    "No relevant tools matched — this capability may not be available."
                ),
            )

        # Build a helpful suggestion message with schemas — content goes in error
        # so _observe() surfaces it to the LLM on failure.
        lines = [
            f"Tool '{tool_name}' not found. Did you mean one of these?",
            "Retry call_tool with the exact tool_name below:",
            "",
        ]
        for _, spec in relevant:
            props = spec.parameters.get("properties", {}) if isinstance(spec.parameters, dict) else {}
            required = set(spec.parameters.get("required", [])) if isinstance(spec.parameters, dict) else set()
            lines.append(f"tool_name: {spec.name}")
            lines.append(f"  description: {spec.description}")
            if props:
                for pname, pdef in props.items():
                    ptype = pdef.get("type", "any") if isinstance(pdef, dict) else "any"
                    req = " (required)" if pname in required else " (optional)"
                    lines.append(f"  arg {pname}: {ptype}{req}")
            lines.append("")

        return ToolResult(success=False, output="", error="\n".join(lines).strip())
