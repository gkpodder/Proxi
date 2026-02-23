"""Tests for proxi.core.state."""

import pytest

from proxi.core.state import AgentStatus, AgentState, Message, TurnState, TurnStatus


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
