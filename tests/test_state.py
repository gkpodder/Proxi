"""Tests for proxi.core.state."""

from pathlib import Path

import pytest

from proxi.core.state import AgentStatus, AgentState, Message, TurnState, TurnStatus, WorkspaceConfig


def test_agent_state_can_continue() -> None:
    """can_continue is True when running and under max_turns."""
    state = AgentState(
        status=AgentStatus.RUNNING,
        max_turns=5,
        current_turn=2,
    )
    assert state.can_continue() is True


def test_agent_state_cannot_continue_when_done() -> None:
    """can_continue is False when status is COMPLETED."""
    state = AgentState(
        status=AgentStatus.COMPLETED,
        max_turns=5,
    )
    assert state.can_continue() is False


def test_agent_state_cannot_continue_at_max_turns() -> None:
    """can_continue is False when current_turn >= max_turns."""
    state = AgentState(
        status=AgentStatus.RUNNING,
        max_turns=5,
        current_turn=5,
    )
    assert state.can_continue() is False


def test_is_done() -> None:
    """is_done is True for COMPLETED, FAILED, CANCELLED."""
    for status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
        state = AgentState(status=status)
        assert state.is_done() is True


def test_is_not_done_when_running() -> None:
    """is_done is False when RUNNING."""
    state = AgentState(status=AgentStatus.RUNNING)
    assert state.is_done() is False


def test_add_message() -> None:
    """add_message appends to history."""
    state = AgentState()
    state.add_message(Message(role="user", content="hello"))
    state.add_message(Message(role="assistant", content="hi"))
    assert len(state.history) == 2
    assert state.history[0].content == "hello"
    assert state.history[1].content == "hi"


def test_get_current_turn() -> None:
    """get_current_turn returns last turn when turns exist."""
    state = AgentState(current_turn=1)
    turn = TurnState(turn_number=1, status=TurnStatus.COMPLETED)
    state.add_turn(turn)
    assert state.get_current_turn() is turn


def test_get_current_turn_empty() -> None:
    """get_current_turn returns None when no turns."""
    state = AgentState()
    assert state.get_current_turn() is None


def test_tool_messages_persist_for_session_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool outputs must be written to history.jsonl so API tool chains survive reload."""
    import proxi.core.state as state_module

    monkeypatch.setattr(state_module._history_writer, "_enabled", False)

    hist = tmp_path / "history.jsonl"
    wc = WorkspaceConfig(
        workspace_root=str(tmp_path),
        agent_id="a",
        session_id="s",
        global_system_prompt_path="",
        soul_path="",
        history_path=str(hist),
        plan_path="",
        todos_path="",
    )
    tool_calls = [
        {
            "id": "call_roundtrip_1",
            "type": "function",
            "function": {"name": "mcp_example", "arguments": "{}"},
        }
    ]
    state = AgentState(workspace=wc, status=AgentStatus.RUNNING)
    state.add_message(Message(role="user", content="run tool pls"))
    state.add_message(Message(role="assistant", content=None, tool_calls=tool_calls))
    state.add_message(
        Message(
            role="tool",
            content='{"result":"ok"}',
            tool_call_id="call_roundtrip_1",
            name="mcp_example",
        )
    )

    loaded = AgentState.load(hist)
    assert loaded is not None
    assert len(loaded.history) == 3
    assert loaded.history[2].role == "tool"
    assert loaded.history[2].tool_call_id == "call_roundtrip_1"
    assert loaded.history[1].tool_calls is not None


def test_load_repairs_assistant_tool_calls_without_saved_tool_rows(tmp_path: Path) -> None:
    """Legacy history.jsonl without tool rows still loads for the Responses API."""
    hist = tmp_path / "history.jsonl"
    lines = [
        '{"role":"user","content":"weather?"}',
        '{"role":"assistant","content":null,"tool_calls":[{"id":"call_orphan","type":"function",'
        '"function":{"name":"mcp_weather_get_current","arguments":"{}"}}]}',
    ]
    hist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    loaded = AgentState.load(hist)
    assert loaded is not None
    assert len(loaded.history) == 3
    assert loaded.history[2].role == "tool"
    assert loaded.history[2].tool_call_id == "call_orphan"
    assert "missing from saved session" in (loaded.history[2].content or "")
