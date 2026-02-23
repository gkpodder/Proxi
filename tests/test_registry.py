"""Tests for proxi.tools.registry.ToolRegistry."""

import pytest

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.registry import ToolRegistry


class DummyTool(BaseTool):
    """Minimal tool for testing."""

    def __init__(self) -> None:
        super().__init__(
            name="dummy",
            description="A test tool",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult(success=True, output="ok", metadata={"args": arguments})


@pytest.mark.asyncio
async def test_register_and_execute() -> None:
    """Registered tool can be executed."""
    reg = ToolRegistry()
    reg.register(DummyTool())
    result = await reg.execute("dummy", {"key": "value"})
    assert result.success is True
    assert result.output == "ok"


@pytest.mark.asyncio
async def test_execute_unknown_tool() -> None:
    """Execute returns error for unknown tool."""
    reg = ToolRegistry()
    result = await reg.execute("nonexistent", {})
    assert result.success is False
    assert "not found" in (result.error or "")


def test_to_specs_includes_registered_tools() -> None:
    """to_specs returns specs for registered tools."""
    reg = ToolRegistry()
    reg.register(DummyTool())
    specs = reg.to_specs()
    assert len(specs) == 1
    assert specs[0].name == "dummy"
