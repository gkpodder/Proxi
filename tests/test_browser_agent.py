"""Tests for the browser automation module.

Tests cover:
- LLM factory creates a browser-use native model (has .provider + .model attrs)
- BrowserSubAgent registers with correct name/schema
- Agent gracefully handles missing API keys
- Agent gracefully handles missing browser-use library
- BrowserProfile uses the Proxi-specific profile path (not the user's Chrome)
- Individual browser tools register in deferred tier
- Tool parameter schemas are valid JSON schemas
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxi.agents.base import AgentContext, SubAgentResult
from proxi.agents.registry import SubAgentRegistry
from proxi.browser.agent import BrowserSubAgent, _PROFILE_DIR, _make_browser_use_llm
from proxi.browser.tools import BROWSER_TOOL_CLASSES, register_browser_tools
from proxi.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- #
# LLM factory tests                                                              #
# --------------------------------------------------------------------------- #


class TestMakeBrowserUseLlm:
    """_make_browser_use_llm() must return a browser-use native model."""

    def _fake_openai_llm(self) -> MagicMock:
        llm = MagicMock()
        llm.provider = "openai"
        llm.model = "gpt-4o"
        return llm

    def _fake_anthropic_llm(self) -> MagicMock:
        llm = MagicMock()
        llm.provider = "anthropic"
        llm.model = "claude-3-5-sonnet-20241022"
        return llm

    def test_uses_anthropic_when_key_available(self) -> None:
        """Prefers Anthropic when ANTHROPIC_API_KEY is in the key store."""
        fake_llm = self._fake_anthropic_llm()
        FakeChatAnthropic = MagicMock(return_value=fake_llm)

        with (
            patch("proxi.browser.agent.get_key_value", side_effect=lambda k: "sk-ant" if k == "ANTHROPIC_API_KEY" else None),
            patch.dict(sys.modules, {"browser_use.llm.anthropic.chat": MagicMock(ChatAnthropic=FakeChatAnthropic)}),
        ):
            llm = _make_browser_use_llm()

        assert hasattr(llm, "provider"), "LLM must have .provider (browser-use contract)"
        assert hasattr(llm, "model"), "LLM must have .model"
        assert llm.provider == "anthropic"

    def test_falls_back_to_openai(self) -> None:
        """Falls back to OpenAI when only OPENAI_API_KEY is available."""
        fake_llm = self._fake_openai_llm()
        FakeChatOpenAI = MagicMock(return_value=fake_llm)

        def _key(k: str) -> str | None:
            return "sk-oai" if k == "OPENAI_API_KEY" else None

        with (
            patch("proxi.browser.agent.get_key_value", side_effect=_key),
            patch.dict(
                sys.modules,
                {
                    "browser_use.llm.anthropic.chat": MagicMock(ChatAnthropic=MagicMock(side_effect=ImportError)),
                    "browser_use.llm.openai.chat": MagicMock(ChatOpenAI=FakeChatOpenAI),
                },
            ),
        ):
            llm = _make_browser_use_llm()

        assert llm.provider == "openai"

    def test_raises_when_no_keys(self) -> None:
        """Raises ValueError when neither key is set."""
        with (
            patch("proxi.browser.agent.get_key_value", return_value=None),
        ):
            with pytest.raises(ValueError, match="No LLM available"):
                _make_browser_use_llm()

    def test_real_llm_has_provider_attribute(self) -> None:
        """Integration: the actual browser-use ChatOpenAI has .provider."""
        bu_llm = pytest.importorskip(
            "browser_use.llm.openai.chat",
            reason="browser-use not installed in this Python environment",
        )
        BUChatOpenAI = bu_llm.ChatOpenAI

        # Instantiate with a dummy key — we only care about the .provider contract.
        llm = BUChatOpenAI(api_key="sk-test-dummy", model="gpt-4o")
        assert hasattr(llm, "provider"), (
            "browser_use.llm.openai.chat.ChatOpenAI must have .provider"
        )
        assert llm.provider == "openai"


# --------------------------------------------------------------------------- #
# BrowserSubAgent registration & schema tests                                   #
# --------------------------------------------------------------------------- #


class TestBrowserSubAgentRegistration:
    def test_name(self) -> None:
        agent = BrowserSubAgent()
        assert agent.name == "browser"

    def test_registers_in_registry(self) -> None:
        registry = SubAgentRegistry()
        agent = BrowserSubAgent()
        registry.register(agent)
        specs = registry.to_specs()
        names = [s.name for s in specs]
        assert "browser" in names

    def test_input_schema_has_required_task(self) -> None:
        agent = BrowserSubAgent()
        schema = agent.input_schema
        assert "task" in schema.get("properties", {})
        assert "task" in schema.get("required", [])

    def test_input_schema_has_optional_fields(self) -> None:
        agent = BrowserSubAgent()
        props = agent.input_schema.get("properties", {})
        assert "start_url" in props
        assert "max_steps" in props

    def test_description_is_informative(self) -> None:
        agent = BrowserSubAgent()
        desc = agent.description.lower()
        # Should mention key use-cases
        assert "flight" in desc or "browser" in desc
        assert len(agent.description) > 50


# --------------------------------------------------------------------------- #
# BrowserSubAgent.run() error-path tests (no real browser)                      #
# --------------------------------------------------------------------------- #


class TestBrowserSubAgentRun:
    def _ctx(self, task: str = "test task", **kwargs: Any) -> AgentContext:
        return AgentContext(task=task, context_refs={"task": task, **kwargs})

    @pytest.mark.asyncio
    async def test_returns_error_when_browser_use_missing(self) -> None:
        """Returns a SubAgentResult(success=False) if browser-use isn't installed."""
        agent = BrowserSubAgent()
        with patch.dict(sys.modules, {"browser_use": None}):  # type: ignore[dict-item]
            result = await agent.run(self._ctx("find flights"))

        assert isinstance(result, SubAgentResult)
        assert result.success is False
        assert result.error is not None
        assert "browser-use" in result.error.lower() or "not installed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_returns_error_when_no_api_key(self) -> None:
        """Returns SubAgentResult(success=False) when no API key is configured."""
        agent = BrowserSubAgent()

        # Ensure browser_use module exists but LLM creation fails
        mock_bu = MagicMock()
        mock_bu.Agent = MagicMock()
        with (
            patch.dict(sys.modules, {"browser_use": mock_bu, "browser_use.browser.profile": MagicMock()}),
            patch("proxi.browser.agent.get_key_value", return_value=None),
        ):
            result = await agent.run(self._ctx("find flights"))

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_returns_error_when_task_is_empty(self) -> None:
        """Returns SubAgentResult(success=False) for empty task."""
        agent = BrowserSubAgent()
        ctx = AgentContext(task="", context_refs={})
        result = await agent.run(ctx)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_timeout_handled_gracefully(self) -> None:
        """asyncio.TimeoutError from agent.run() is caught and returned as failure."""
        import asyncio

        agent = BrowserSubAgent()

        mock_history = MagicMock()
        mock_history.final_result.return_value = "done"
        mock_history.urls.return_value = []
        mock_history.number_of_steps.return_value = 1

        async def _slow_run(*args: Any, **kwargs: Any) -> Any:
            raise asyncio.TimeoutError

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = _slow_run

        mock_bu_profile = MagicMock()
        mock_bu_profile.BrowserProfile = MagicMock(return_value=MagicMock())
        mock_bu_agent = MagicMock()
        mock_bu_agent.Agent = MagicMock(return_value=mock_agent_instance)
        fake_llm = MagicMock()
        fake_llm.provider = "openai"
        fake_llm.model = "gpt-4o"

        with (
            patch.dict(
                sys.modules,
                {
                    "browser_use": mock_bu_agent,
                    "browser_use.browser.profile": mock_bu_profile,
                },
            ),
            patch("proxi.browser.agent._make_browser_use_llm", return_value=fake_llm),
        ):
            result = await agent.run(self._ctx("find flights"), max_time=0.001)

        assert result.success is False
        assert "timed out" in (result.error or "").lower() or "timeout" in (result.summary or "").lower()

    @pytest.mark.asyncio
    async def test_successful_run_returns_final_result(self) -> None:
        """A mock successful run returns summary from history.final_result()."""
        agent = BrowserSubAgent()

        mock_history = MagicMock()
        mock_history.final_result.return_value = "Found: RTX 4070 laptop $1,599"
        mock_history.urls.return_value = ["https://bestbuy.com"]
        mock_history.number_of_steps.return_value = 8

        mock_agent_instance = AsyncMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_history)

        mock_bu_profile = MagicMock()
        mock_bu_profile.BrowserProfile = MagicMock(return_value=MagicMock())
        mock_bu_agent = MagicMock()
        mock_bu_agent.Agent = MagicMock(return_value=mock_agent_instance)
        fake_llm = MagicMock()
        fake_llm.provider = "openai"

        with (
            patch.dict(
                sys.modules,
                {
                    "browser_use": mock_bu_agent,
                    "browser_use.browser.profile": mock_bu_profile,
                },
            ),
            patch("proxi.browser.agent._make_browser_use_llm", return_value=fake_llm),
        ):
            result = await agent.run(self._ctx("find gaming laptop"))

        assert result.success is True
        assert "RTX 4070" in result.summary
        assert result.confidence > 0
        assert result.artifacts.get("steps_taken") == 8


# --------------------------------------------------------------------------- #
# Browser profile isolation                                                      #
# --------------------------------------------------------------------------- #


class TestBrowserProfileIsolation:
    def test_profile_dir_is_under_proxi_home(self) -> None:
        """Profile must be under ~/.proxi/ not the user's personal Chrome dirs."""
        assert str(_PROFILE_DIR).endswith("browser_profile")
        assert ".proxi" in str(_PROFILE_DIR)

    def test_profile_dir_not_user_chrome(self) -> None:
        personal_chrome_paths = [
            Path.home() / "Library" / "Application Support" / "Google" / "Chrome",
            Path.home() / ".config" / "google-chrome",
            Path.home() / "AppData" / "Local" / "Google" / "Chrome",
        ]
        for chrome_path in personal_chrome_paths:
            assert not str(_PROFILE_DIR).startswith(str(chrome_path)), (
                f"Proxi must NOT use the user's personal Chrome profile: {chrome_path}"
            )


# --------------------------------------------------------------------------- #
# Individual browser tools tests                                                 #
# --------------------------------------------------------------------------- #


class TestBrowserToolsRegistration:
    def test_all_ten_tools_defined(self) -> None:
        assert len(BROWSER_TOOL_CLASSES) == 10

    def test_expected_tool_names(self) -> None:
        names = {cls().name for cls in BROWSER_TOOL_CLASSES}
        expected = {
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_snapshot",
            "browser_press",
            "browser_back",
            "browser_close",
            "browser_get_images",
            "browser_console",
        }
        assert names == expected

    def test_register_browser_tools_goes_to_deferred_tier(self) -> None:
        registry = ToolRegistry()
        register_browser_tools(registry)
        deferred = set(registry._deferred_tools.keys())
        assert deferred == {
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_snapshot",
            "browser_press",
            "browser_back",
            "browser_close",
            "browser_get_images",
            "browser_console",
        }
        # None should land in the live tier
        assert not any(k.startswith("browser_") for k in registry._tools)

    def test_tools_not_parallel_safe(self) -> None:
        """Browser state is mutable — no tool should be parallel-safe."""
        for cls in BROWSER_TOOL_CLASSES:
            tool = cls()
            assert tool.parallel_safe is False, (
                f"{tool.name} must not be parallel_safe (browser state is mutable)"
            )

    def test_snapshot_is_read_only(self) -> None:
        from proxi.browser.tools import BrowserSnapshotTool
        assert BrowserSnapshotTool().read_only is True

    def test_mutating_tools_not_read_only(self) -> None:
        from proxi.browser.tools import (
            BrowserClickTool,
            BrowserCloseTool,
            BrowserConsoleTool,
            BrowserNavigateTool,
            BrowserPressTool,
            BrowserScrollTool,
            BrowserTypeTool,
        )
        for cls in [
            BrowserNavigateTool,
            BrowserClickTool,
            BrowserTypeTool,
            BrowserScrollTool,
            BrowserPressTool,
            BrowserCloseTool,
            BrowserConsoleTool,
        ]:
            assert cls().read_only is False, f"{cls.__name__} should be read_only=False"

    def test_all_tools_have_valid_schemas(self) -> None:
        """Every tool's parameters_schema must be a valid JSON schema dict."""
        for cls in BROWSER_TOOL_CLASSES:
            tool = cls()
            schema = tool.parameters_schema
            assert isinstance(schema, dict), f"{tool.name}: parameters_schema must be a dict"
            assert schema.get("type") == "object", (
                f"{tool.name}: parameters_schema type must be 'object'"
            )

    def test_required_tools_have_required_params(self) -> None:
        from proxi.browser.tools import (
            BrowserClickTool,
            BrowserConsoleTool,
            BrowserNavigateTool,
            BrowserPressTool,
            BrowserTypeTool,
        )
        # navigate needs url
        assert "url" in BrowserNavigateTool().parameters_schema.get("required", [])
        # click needs selector
        assert "selector" in BrowserClickTool().parameters_schema.get("required", [])
        # type needs selector + text
        required = BrowserTypeTool().parameters_schema.get("required", [])
        assert "selector" in required
        assert "text" in required
        # press needs key
        assert "key" in BrowserPressTool().parameters_schema.get("required", [])
        # console needs javascript
        assert "javascript" in BrowserConsoleTool().parameters_schema.get("required", [])
