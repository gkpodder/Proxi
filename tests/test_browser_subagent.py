"""Tests for BrowserSubAgent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from proxi.agents.base import AgentContext
from proxi.agents.browser import BrowserSubAgent
from proxi.core.state import Message
from proxi.llm.schemas import ModelDecision, ModelResponse, ToolCall, ToolSpec
from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.registry import ToolRegistry


class FakeWebTool(BaseTool):
    """Simple web-like tool for tests."""

    def __init__(self) -> None:
        super().__init__(
            name="fetch_webpage",
            description="Fetch webpage content from URL",
            parameters_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output=f"fetched:{arguments.get('url', '')}")


class FakeNonWebTool(BaseTool):
    """Tool that should not be selected by browser keyword filter."""

    def __init__(self) -> None:
        super().__init__(
            name="read_file",
            description="Read local file",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="ok")


class FakeBrowserNavigateTool(BaseTool):
    """Fake native browser action tool."""

    def __init__(self) -> None:
        super().__init__(
            name="browser_navigate",
            description="Navigate browser session to URL",
            parameters_schema={"type": "object", "properties": {"url": {"type": "string"}}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="navigated", metadata={"url": arguments.get("url")})


class FakeBrowserScreenshotTool(BaseTool):
    """Fake screenshot tool used by verifier path."""

    def __init__(self) -> None:
        super().__init__(
            name="browser_screenshot",
            description="Take screenshot for browser verification",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=True,
            output="ok",
            metadata={"image_base64": "ZmFrZS1pbWFnZQ=="},
        )


class FakeLLM:
    """Deterministic LLM that first calls tool, then responds."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents=None,
        system: str | None = None,
    ) -> ModelResponse:
        self.calls += 1
        assert tools is not None

        if self.calls == 1:
            return ModelResponse(
                decision=ModelDecision.tool_call(
                    ToolCall(
                        id="tc-1",
                        name="fetch_webpage",
                        arguments={"url": "https://example.com"},
                    )
                ),
                usage={"total_tokens": 20},
                finish_reason="tool_calls",
            )

        return ModelResponse(
            decision=ModelDecision.respond("Done browsing."),
            usage={"total_tokens": 10},
            finish_reason="stop",
        )


class FakeVerifier:
    """Fake verifier for browser action validation path."""

    model = "gpt-4o-mini"

    async def verify_action(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "enabled": True,
            "verified": True,
            "passed": True,
            "confidence": 0.88,
            "reason": "Page appears to have navigated correctly.",
            "model": self.model,
        }


class FakeBrowserLLM:
    """Deterministic LLM that calls browser_navigate then responds."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        agents=None,
        system: str | None = None,
    ) -> ModelResponse:
        self.calls += 1
        assert tools is not None

        if self.calls == 1:
            return ModelResponse(
                decision=ModelDecision.tool_call(
                    ToolCall(
                        id="tc-browser-1",
                        name="browser_navigate",
                        arguments={"url": "https://example.com"},
                    )
                ),
                usage={"total_tokens": 20},
                finish_reason="tool_calls",
            )

        return ModelResponse(
            decision=ModelDecision.respond("Done browsing."),
            usage={"total_tokens": 10},
            finish_reason="stop",
        )


@pytest.mark.asyncio
async def test_browser_subagent_executes_web_tool() -> None:
    """Browser sub-agent executes selected web tools and completes."""
    registry = ToolRegistry()
    registry.register(FakeWebTool())

    agent = BrowserSubAgent(llm_client=FakeLLM(), tool_registry=registry)
    result = await agent.run(AgentContext(task="Research example website"))

    assert result.success is True
    assert "Done browsing." in result.summary
    assert result.artifacts["actions"][0]["tool"] == "fetch_webpage"


@pytest.mark.asyncio
async def test_browser_subagent_fails_without_web_tools() -> None:
    """Browser sub-agent fails fast when no web tool is configured."""
    registry = ToolRegistry()
    registry.register(FakeNonWebTool())

    agent = BrowserSubAgent(llm_client=FakeLLM(), tool_registry=registry)
    result = await agent.run(AgentContext(task="Find flights to Tokyo"))

    assert result.success is False
    assert "No web tools available" in (result.error or "")


@pytest.mark.asyncio
async def test_browser_subagent_emits_progress() -> None:
    """Browser sub-agent sends progress events through optional hook."""
    registry = ToolRegistry()
    registry.register(FakeWebTool())

    agent = BrowserSubAgent(llm_client=FakeLLM(), tool_registry=registry)

    events: list[dict[str, Any]] = []

    def hook(payload: dict[str, Any]) -> None:
        events.append(payload)

    context = AgentContext(
        task="Open example and summarize",
        context_refs={"__progress_hook__": hook},
    )
    result = await agent.run(context)

    assert result.success is True
    assert any(e.get("event") == "browser_loop_start" for e in events)
    assert any(e.get("event") == "browser_tool_done" for e in events)


@pytest.mark.asyncio
async def test_browser_subagent_runs_vision_verification() -> None:
    """Browser sub-agent runs vision verification for native browser tools."""
    registry = ToolRegistry()
    registry.register(FakeBrowserNavigateTool())
    registry.register(FakeBrowserScreenshotTool())

    agent = BrowserSubAgent(
        llm_client=FakeBrowserLLM(),
        tool_registry=registry,
        vision_verifier=FakeVerifier(),
        max_vision_checks=2,
    )

    result = await agent.run(AgentContext(task="Open example.com"))

    assert result.success is True
    assert result.artifacts["verification"]["checks_used"] == 1
    assert result.artifacts["actions"][0]["verification"]["passed"] is True
