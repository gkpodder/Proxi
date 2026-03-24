"""Tests for proxi.workspace.WorkspaceManager."""

from pathlib import Path

import pytest

from proxi.workspace import AgentInfo, WorkspaceError, WorkspaceManager


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
    )
    assert isinstance(info, AgentInfo)
    assert info.agent_id == "test-agent"
    assert (info.path / "Soul.md").exists()
    assert "Test Agent" in (info.path / "Soul.md").read_text()
    gw = mgr.root / "gateway.yml"
    assert gw.exists()
    text = gw.read_text(encoding="utf-8")
    assert "test-agent:" in text
    assert "agents/test-agent/Soul.md" in text
    assert "default_session" in text


def test_create_agent_with_explicit_id(proxi_home_env: Path) -> None:
    """create_agent accepts explicit agent_id."""
    mgr = WorkspaceManager()
    info = mgr.create_agent(
        name="Custom",
        persona="x",
        agent_id="my-agent",
    )
    assert info.agent_id == "my-agent"


def test_list_agents_after_create(proxi_home_env: Path) -> None:
    """list_agents returns created agents."""
    mgr = WorkspaceManager()
    mgr.create_agent(name="A", persona="x")
    mgr.create_agent(name="B", persona="x", agent_id="b")
    agents = mgr.list_agents()
    assert len(agents) == 2
    ids = {a.agent_id for a in agents}
    assert "a" in ids
    assert "b" in ids


def test_create_single_session(proxi_home_env: Path) -> None:
    """create_single_session creates session dir and history file."""
    mgr = WorkspaceManager()
    agent = mgr.create_agent(name="S", persona="x")
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


def test_delete_agent_removes_folder_and_gateway(proxi_home_env: Path) -> None:
    """delete_agent removes gateway entry and ~/.proxi/agents/<id>."""
    mgr = WorkspaceManager()
    mgr.create_agent(name="One", persona="a", agent_id="one")
    mgr.create_agent(name="Two", persona="b", agent_id="two")
    assert (mgr.agents_dir / "one").exists()
    mgr.delete_agent("one")
    assert not (mgr.agents_dir / "one").exists()
    assert (mgr.agents_dir / "two").exists()
    text = (mgr.root / "gateway.yml").read_text(encoding="utf-8")
    assert "two:" in text
    assert "one:" not in text


def test_delete_last_agent_fails(proxi_home_env: Path) -> None:
    """Cannot delete the only agent in gateway.yml."""
    mgr = WorkspaceManager()
    mgr.create_agent(name="Only", persona="x", agent_id="only")
    with pytest.raises(WorkspaceError, match="last agent"):
        mgr.delete_agent("only")
