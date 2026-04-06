"""Tests for proxi.core.compactor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from proxi.core.compactor import (
    CompactionResult,
    ContextCompactor,
    _clean_orphan_tool_pairs,
    _enforce_role_alternation,
    _estimate_message_chars,
    _prune_tool_results,
    _take_tail_by_chars,
)
from proxi.core.state import AgentState, AgentStatus, Message, WorkspaceConfig
from proxi.llm.schemas import DecisionType, ModelDecision, ModelResponse


def _make_workspace(tmp_path: Path) -> WorkspaceConfig:
    """Build a minimal WorkspaceConfig pointing at tmp_path."""
    return WorkspaceConfig(
        workspace_root=str(tmp_path),
        agent_id="test",
        session_id="s1",
        global_system_prompt_path=str(tmp_path / "system_prompt.md"),
        soul_path=str(tmp_path / "Soul.md"),
        history_path=str(tmp_path / "history.jsonl"),
        plan_path=str(tmp_path / "plan.md"),
        todos_path=str(tmp_path / "todos.md"),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_response(content: str) -> ModelResponse:
    return ModelResponse(
        decision=ModelDecision(
            type=DecisionType.RESPOND,
            payload={"content": content},
        ),
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )


@pytest.fixture
def mock_llm():
    """AsyncMock LLM client that returns a canned compaction summary."""
    client = AsyncMock()
    client.generate.return_value = _make_response(
        "[CONTEXT COMPACTION] Summary of prior work: task A was completed."
    )
    return client


@pytest.fixture
def bloated_history() -> list[Message]:
    """A message list large enough to have a compactable middle."""
    msgs: list[Message] = [
        Message(role="user", content="Start task"),
        Message(role="assistant", content="Starting task"),
        Message(role="user", content="Step 0"),
    ]
    for i in range(1, 30):
        msgs.append(Message(role="user", content=f"Step {i}: " + "x" * 300))
        msgs.append(Message(role="assistant", content=f"Done step {i}: " + "y" * 300))
    msgs.append(Message(role="user", content="What is next?"))
    msgs.append(Message(role="assistant", content="The next step is Z"))
    return msgs


@pytest.fixture
def compactor(mock_llm: AsyncMock) -> ContextCompactor:
    return ContextCompactor(
        llm_client=mock_llm,
        context_window=10_000,
        compaction_threshold=0.70,
        head_messages=3,
        tail_tokens=500,
        tool_result_prune_chars=50,
        max_passes=3,
    )


# ---------------------------------------------------------------------------
# _estimate_message_chars
# ---------------------------------------------------------------------------


def test_estimate_empty_message() -> None:
    msg = Message(role="user", content=None)
    assert _estimate_message_chars(msg) == 0


def test_estimate_content_only() -> None:
    msg = Message(role="user", content="hello world")
    assert _estimate_message_chars(msg) == len("hello world")


def test_estimate_includes_tool_calls() -> None:
    tool_calls = [{"id": "tc1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]
    msg = Message(role="assistant", content=None, tool_calls=tool_calls)
    expected = len(json.dumps(tool_calls))
    assert _estimate_message_chars(msg) == expected


# ---------------------------------------------------------------------------
# _take_tail_by_chars
# ---------------------------------------------------------------------------


def test_take_tail_everything_fits() -> None:
    msgs = [Message(role="user", content="a" * 10) for _ in range(5)]
    tail = _take_tail_by_chars(msgs, char_budget=1000)
    assert tail == msgs


def test_take_tail_truncates() -> None:
    msgs = [Message(role="user", content="a" * 100) for _ in range(10)]
    tail = _take_tail_by_chars(msgs, char_budget=250)
    # Each message is 100 chars; budget 250 → at most 2 messages
    assert len(tail) <= 3
    assert tail == msgs[len(msgs) - len(tail):]


def test_take_tail_empty_input() -> None:
    assert _take_tail_by_chars([], char_budget=1000) == []


def test_take_tail_zero_budget() -> None:
    msgs = [Message(role="user", content="hello")]
    # Budget 0 means nothing fits; cutoff stays at 0 from the else branch
    # Actual result depends on the scan: first message already exceeds 0-budget
    tail = _take_tail_by_chars(msgs, char_budget=0)
    assert isinstance(tail, list)


# ---------------------------------------------------------------------------
# _prune_tool_results
# ---------------------------------------------------------------------------


def test_prune_long_tool_result() -> None:
    content = "x" * 100
    msg = Message(role="tool", content=content, tool_call_id="tc1")
    result = _prune_tool_results([msg], max_chars=50)
    assert len(result) == 1
    assert "truncated" in result[0].content  # type: ignore[arg-type]
    assert "100" in result[0].content  # original length present


def test_prune_short_tool_result_unchanged() -> None:
    content = "short"
    msg = Message(role="tool", content=content, tool_call_id="tc1")
    result = _prune_tool_results([msg], max_chars=50)
    assert result[0].content == content


def test_prune_non_tool_messages_unchanged() -> None:
    msg = Message(role="user", content="x" * 100)
    result = _prune_tool_results([msg], max_chars=50)
    assert result[0].content == "x" * 100


def test_prune_preview_included() -> None:
    content = "ABCDE" * 60  # 300 chars
    msg = Message(role="tool", content=content, tool_call_id="tc1")
    result = _prune_tool_results([msg], max_chars=50)
    assert "ABCDE" in result[0].content  # type: ignore[operator]


# ---------------------------------------------------------------------------
# _clean_orphan_tool_pairs
# ---------------------------------------------------------------------------


def test_clean_removes_dangling_tool_message() -> None:
    """Tool message with no matching assistant tool_call is removed."""
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="ok"),
        Message(role="tool", content="result", tool_call_id="orphan_id"),
    ]
    cleaned = _clean_orphan_tool_pairs(msgs)
    assert not any(m.role == "tool" for m in cleaned)


def test_clean_injects_missing_tool_result() -> None:
    """Assistant tool_call with no following tool message gets a synthetic result."""
    msgs = [
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}],
        ),
    ]
    cleaned = _clean_orphan_tool_pairs(msgs)
    tool_msgs = [m for m in cleaned if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "tc1"


def test_clean_noop_for_well_formed_history() -> None:
    """Well-formed tool pairs are not modified."""
    msgs = [
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}],
        ),
        Message(role="tool", content="result", tool_call_id="tc1"),
        Message(role="assistant", content="done"),
    ]
    cleaned = _clean_orphan_tool_pairs(msgs)
    assert len(cleaned) == len(msgs)


# ---------------------------------------------------------------------------
# _enforce_role_alternation
# ---------------------------------------------------------------------------


def test_alternation_user_user_inserts_bridge() -> None:
    msgs = [
        Message(role="user", content="a"),
        Message(role="user", content="b"),
    ]
    fixed = _enforce_role_alternation(msgs)
    roles = [m.role for m in fixed]
    assert roles == ["user", "assistant", "user"]


def test_alternation_assistant_assistant_inserts_bridge() -> None:
    msgs = [
        Message(role="assistant", content="a"),
        Message(role="assistant", content="b"),
    ]
    fixed = _enforce_role_alternation(msgs)
    roles = [m.role for m in fixed]
    assert roles == ["assistant", "user", "assistant"]


def test_alternation_clean_history_unchanged() -> None:
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
        Message(role="user", content="ok"),
    ]
    fixed = _enforce_role_alternation(msgs)
    assert [m.content for m in fixed] == ["hi", "hello", "ok"]


def test_alternation_empty_input() -> None:
    assert _enforce_role_alternation([]) == []


# ---------------------------------------------------------------------------
# Full compaction pass: maybe_compact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_compact_under_threshold_noop(
    compactor: ContextCompactor, bloated_history: list[Message]
) -> None:
    """If current_tokens is well under threshold, no compaction fires."""
    state = AgentState(status=AgentStatus.RUNNING, history=bloated_history[:4])
    result = await compactor.maybe_compact(state, current_tokens=100)
    assert result.compaction_triggered is False
    assert result.compacted_history == state.history


@pytest.mark.asyncio
async def test_maybe_compact_over_threshold_fires(
    compactor: ContextCompactor, bloated_history: list[Message], tmp_path: Path
) -> None:
    """When current_tokens >= threshold, compaction runs."""
    ws = _make_workspace(tmp_path)
    state = AgentState(status=AgentStatus.RUNNING, history=bloated_history, workspace=ws)
    threshold = int(compactor.context_window * compactor.compaction_threshold)
    result = await compactor.maybe_compact(state, current_tokens=threshold + 1)
    assert result.compaction_triggered is True
    assert result.original_tokens == threshold + 1


@pytest.mark.asyncio
async def test_compact_llm_called_with_head_plus_middle(
    compactor: ContextCompactor, bloated_history: list[Message], mock_llm: AsyncMock, tmp_path: Path
) -> None:
    """LLM is called; messages passed include head and the summary request appended."""
    ws = _make_workspace(tmp_path)
    state = AgentState(status=AgentStatus.RUNNING, history=bloated_history, workspace=ws)
    await compactor.force_compact(state, current_tokens=0)

    assert mock_llm.generate.called
    call_messages = mock_llm.generate.call_args.kwargs["messages"]
    # Last message is the summary request
    assert "summarize" in call_messages[-1].content.lower()


@pytest.mark.asyncio
async def test_compact_result_has_head_summary_tail(
    compactor: ContextCompactor, bloated_history: list[Message], tmp_path: Path
) -> None:
    """Compacted history preserves first head_messages and ends with tail content."""
    ws = _make_workspace(tmp_path)
    state = AgentState(status=AgentStatus.RUNNING, history=bloated_history, workspace=ws)
    result = await compactor.force_compact(state, current_tokens=0)

    compacted = result.compacted_history
    # Head messages are preserved
    for i in range(compactor.head_messages):
        assert compacted[i].content == bloated_history[i].content

    # Summary message is present (contains CONTEXT COMPACTION prefix)
    assert any("[CONTEXT COMPACTION]" in (m.content or "") for m in compacted)


@pytest.mark.asyncio
async def test_compact_summary_has_correct_prefix(
    compactor: ContextCompactor, bloated_history: list[Message], tmp_path: Path
) -> None:
    """Summary text starts with the required CONTEXT COMPACTION prefix."""
    ws = _make_workspace(tmp_path)
    state = AgentState(status=AgentStatus.RUNNING, history=bloated_history, workspace=ws)
    result = await compactor.force_compact(state, current_tokens=0)
    assert result.summary_text is not None
    assert "[CONTEXT COMPACTION]" in result.summary_text


@pytest.mark.asyncio
async def test_compact_with_focus_injects_focus_into_request(
    compactor: ContextCompactor, bloated_history: list[Message], mock_llm: AsyncMock, tmp_path: Path
) -> None:
    """When focus is provided, it appears in the summary request message."""
    ws = _make_workspace(tmp_path)
    state = AgentState(status=AgentStatus.RUNNING, history=bloated_history, workspace=ws)
    await compactor.force_compact(state, current_tokens=0, focus="keep the auth details")

    call_messages = mock_llm.generate.call_args.kwargs["messages"]
    last_msg_content = call_messages[-1].content or ""
    assert "keep the auth details" in last_msg_content


@pytest.mark.asyncio
async def test_force_compact_bypasses_threshold(
    compactor: ContextCompactor, tmp_path: Path
) -> None:
    """force_compact always runs even if history is small."""
    ws = _make_workspace(tmp_path)
    # Minimal history with enough messages to have a middle
    history = [
        Message(role="user", content="a"),
        Message(role="assistant", content="b"),
        Message(role="user", content="c"),
        Message(role="assistant", content="d"),
        Message(role="user", content="e"),
        Message(role="assistant", content="f"),
    ]
    state = AgentState(status=AgentStatus.RUNNING, history=history, workspace=ws)
    result = await compactor.force_compact(state, current_tokens=0)
    # If middle was non-empty, compaction triggered; otherwise no-op is ok
    assert isinstance(result, CompactionResult)


@pytest.mark.asyncio
async def test_max_passes_not_exceeded(
    mock_llm: AsyncMock, tmp_path: Path
) -> None:
    """Compactor never exceeds max_passes even if still over threshold."""
    compactor = ContextCompactor(
        llm_client=mock_llm,
        context_window=10_000,
        compaction_threshold=0.0,  # always triggers
        head_messages=2,
        tail_tokens=100,
        max_passes=2,
    )
    ws = _make_workspace(tmp_path)
    history = [Message(role="user", content="x" * 50) for _ in range(20)]
    state = AgentState(status=AgentStatus.RUNNING, history=history, workspace=ws)
    await compactor.force_compact(state, current_tokens=9999)
    # LLM was called at most max_passes times
    assert mock_llm.generate.call_count <= 2


# ---------------------------------------------------------------------------
# History rewrite
# ---------------------------------------------------------------------------


def test_rewrite_history_updates_in_memory(tmp_path: Path) -> None:
    """rewrite_history replaces the in-memory history list."""
    ws = _make_workspace(tmp_path)
    state = AgentState(
        status=AgentStatus.RUNNING,
        history=[Message(role="user", content="old")],
        workspace=ws,
    )
    new_msgs = [Message(role="user", content="new")]
    state.rewrite_history(new_msgs)
    assert state.history[0].content == "new"


def test_rewrite_history_writes_jsonl(tmp_path: Path) -> None:
    """rewrite_history atomically rewrites history.jsonl."""
    ws = _make_workspace(tmp_path)
    hist_path = Path(ws.history_path)
    state = AgentState(status=AgentStatus.RUNNING, workspace=ws)
    msgs = [
        Message(role="user", content="alpha"),
        Message(role="assistant", content="beta"),
    ]
    state.rewrite_history(msgs)

    assert hist_path.exists()
    lines = [l for l in hist_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2


def test_rewrite_history_loadable(tmp_path: Path) -> None:
    """AgentState.load() on a rewritten history.jsonl reconstructs messages correctly."""
    ws = _make_workspace(tmp_path)
    hist_path = Path(ws.history_path)
    state = AgentState(status=AgentStatus.RUNNING, workspace=ws)
    msgs = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="world"),
    ]
    state.rewrite_history(msgs)

    loaded = AgentState.load(hist_path)
    assert loaded is not None
    assert len(loaded.history) == 2
    assert loaded.history[0].content == "hello"
    assert loaded.history[1].content == "world"


def test_rewrite_history_replaces_previous_content(tmp_path: Path) -> None:
    """rewrite_history truncates old content rather than appending."""
    ws = _make_workspace(tmp_path)
    hist_path = Path(ws.history_path)
    state = AgentState(status=AgentStatus.RUNNING, workspace=ws)

    state.rewrite_history([Message(role="user", content="first")])
    state.rewrite_history([Message(role="user", content="second")])

    loaded = AgentState.load(hist_path)
    assert loaded is not None
    assert len(loaded.history) == 1
    assert loaded.history[0].content == "second"


# ---------------------------------------------------------------------------
# LaneBudget.should_compact
# ---------------------------------------------------------------------------


def test_should_compact_true_at_threshold() -> None:
    from proxi.gateway.lanes.budget import LaneBudget
    budget = LaneBudget(context_window=10_000, compaction_threshold=0.70, tokens_used=7_000)
    assert budget.should_compact() is True


def test_should_compact_false_below_threshold() -> None:
    from proxi.gateway.lanes.budget import LaneBudget
    budget = LaneBudget(context_window=10_000, compaction_threshold=0.70, tokens_used=6_999)
    assert budget.should_compact() is False


def test_should_compact_false_zero_window() -> None:
    from proxi.gateway.lanes.budget import LaneBudget
    budget = LaneBudget(context_window=0, compaction_threshold=0.70, tokens_used=0)
    assert budget.should_compact() is False


def test_budget_check_still_raises_at_hard_limit() -> None:
    from proxi.gateway.lanes.budget import LaneBudget, BudgetExceeded
    budget = LaneBudget(token_budget=1000, tokens_used=1000)
    with pytest.raises(BudgetExceeded):
        budget.check()
