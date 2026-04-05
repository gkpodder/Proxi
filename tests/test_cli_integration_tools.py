"""Tests for CLI integration tool gating and Spotify MCP catalog routing."""

import pytest

from proxi.cli.main import auto_load_cli_tools, build_cli_tool_lists
from proxi.integrations.catalog import tool_integration
from proxi.mcp.servers.spotify_server import SPOTIFY_TOOLS
from proxi.tools.registry import ToolRegistry


def _sample_integrations_config() -> dict:
    return {
        "integrations": {
            "gmail": {
                "type": "cli",
                "defer_loading": True,
                "always_load": ["read_emails"],
            },
            "weather": {
                "type": "cli",
                "defer_loading": False,
                "always_load": ["get_weather"],
            },
        }
    }


def test_build_cli_tool_lists_gmail_disabled() -> None:
    cfg = _sample_integrations_config()
    live, deff = build_cli_tool_lists(
        config=cfg,
        enabled_integration_names=set(),
    )
    names = {t.name for t in live} | {t.name for t in deff}
    assert "read_emails" not in names
    assert "send_email" not in names


def test_build_cli_tool_lists_gmail_enabled_read_emails_live() -> None:
    cfg = _sample_integrations_config()
    live, deff = build_cli_tool_lists(
        config=cfg,
        enabled_integration_names={"gmail"},
    )
    live_names = {t.name for t in live}
    deferred_names = {t.name for t in deff}
    assert "read_emails" in live_names
    assert "send_email" in deferred_names


def test_build_cli_tool_lists_skips_integration_missing_from_config() -> None:
    """Tools with integration_name not in JSON must not be treated as core."""
    cfg: dict = {"integrations": {}}
    live, deff = build_cli_tool_lists(
        config=cfg,
        enabled_integration_names={"gmail"},
    )
    names = {t.name for t in live} | {t.name for t in deff}
    assert "read_emails" not in names


def test_auto_load_cli_tools_respects_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    db = tmp_path / "api_keys.db"
    from proxi.security.key_store import enable_integration, init_db

    init_db(db)
    reg = ToolRegistry()
    monkeypatch.setattr(
        "proxi.cli.main.load_integrations_config",
        lambda: _sample_integrations_config(),
    )
    auto_load_cli_tools(reg, db_path=db)
    assert "read_emails" not in reg._tools
    assert "read_emails" not in reg._deferred_tools

    enable_integration("gmail", True, db_path=db)
    reg2 = ToolRegistry()
    auto_load_cli_tools(reg2, db_path=db)
    assert "read_emails" in reg2._tools


@pytest.mark.parametrize("entry", SPOTIFY_TOOLS, ids=lambda e: e["name"])
def test_spotify_mcp_tool_names_route_to_spotify_integration(entry: dict) -> None:
    name = entry["name"]
    assert tool_integration(name) == "spotify", f"{name} must map for MCP enable gating"


@pytest.mark.asyncio
async def test_auto_load_mcp_skips_when_integration_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from proxi.cli.main import auto_load_mcp_servers

    monkeypatch.setattr(
        "proxi.security.key_store.get_enabled_integrations",
        lambda db_path=None: [],
    )
    monkeypatch.setattr(
        "proxi.cli.main.load_integrations_config",
        lambda: {
            "integrations": {
                "spotify": {
                    "type": "mcp",
                    "command": "uv",
                    "args": ["run", "python", "-c", "raise SystemExit(1)"],
                }
            }
        },
    )
    reg = ToolRegistry()
    adapters = await auto_load_mcp_servers(reg)
    assert adapters == []
    assert not reg._tools
    assert not reg._deferred_tools
