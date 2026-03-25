"""Tests for proxi.workspace.WorkspaceManager."""

from pathlib import Path

import pytest

from proxi.workspace import AgentInfo, WorkspaceManager


def test_list_agents_empty(proxi_home_env: Path) -> None:
    """list_agents returns empty when no agents exist."""
    mgr = WorkspaceManager()
    assert mgr.list_agents() == []


def test_create_agent(proxi_home_env: Path) -> None:
    """create_agent creates directory and Soul.md."""
    mgr = WorkspaceManager()
    info = mgr.create_agent(
        name="Test Agent",
        persona="Helpful",
        mission="Assist users",
    )
    assert isinstance(info, AgentInfo)
    assert info.agent_id == "test-agent"
    assert (info.path / "Soul.md").exists()
    assert "Test Agent" in (info.path / "Soul.md").read_text()


def test_create_agent_with_explicit_id(proxi_home_env: Path) -> None:
    """create_agent accepts explicit agent_id."""
    mgr = WorkspaceManager()
    info = mgr.create_agent(
        name="Custom",
        persona="x",
        mission="y",
        agent_id="my-agent",
    )
    assert info.agent_id == "my-agent"


def test_list_agents_after_create(proxi_home_env: Path) -> None:
    """list_agents returns created agents."""
    mgr = WorkspaceManager()
    mgr.create_agent(name="A", persona="x", mission="y")
    mgr.create_agent(name="B", persona="x", mission="y", agent_id="b")
    agents = mgr.list_agents()
    assert len(agents) == 2
    ids = {a.agent_id for a in agents}
    assert "a" in ids
    assert "b" in ids


def test_create_single_session(proxi_home_env: Path) -> None:
    """create_single_session creates session dir and history file."""
    mgr = WorkspaceManager()
    agent = mgr.create_agent(name="S", persona="x", mission="y")
    session = mgr.create_single_session(agent)
    assert session.session_dir.exists()
    assert session.history_path.exists()
    assert session.history_path.read_text() == ""


def test_ensure_global_system_prompt(proxi_home_env: Path) -> None:
    """ensure_global_system_prompt creates system_prompt.md."""
    mgr = WorkspaceManager()
    path = mgr.ensure_global_system_prompt()
    assert path.exists()
    assert "Proxi" in path.read_text()


def test_slugify() -> None:
    """_slugify produces filesystem-safe slugs."""
    assert WorkspaceManager._slugify("Hello World") == "hello-world"
    assert WorkspaceManager._slugify("Test Agent 123") == "test-agent-123"
    assert WorkspaceManager._slugify("  ") == ""
