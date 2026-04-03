"""Context compaction for long-running agent sessions.

Implements a head / middle / tail compression algorithm:
  1. Prune large tool results in the middle (no LLM call).
  2. Protect the head (first N messages anchoring the task).
  3. Protect the tail (~20K token equivalent of recent context).
  4. Summarise the middle via a cache-safe LLM fork (same system prompt +
     same head/middle prefix → parent prompt cache is reused; only the
     summary request itself costs new tokens).
  5. Assemble: head + summary_message + tail.
  6. Enforce strict user/assistant role alternation.
  7. Clean up orphaned tool_call / tool_result pairs.
  8. Optionally re-inject workspace todos/plan after compaction.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from proxi.core.state import AgentState, Message
from proxi.llm.base import LLMClient
from proxi.llm.model_registry import DEFAULT_COMPACTION_THRESHOLD
from proxi.observability.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION] Earlier turns in this conversation were compacted "
    "to save context space. The summary below describes work that was "
    "already completed, and the current session state may still reflect "
    "that work (for example, files may already be changed). Use the summary "
    "and the current state to continue from where things left off, and "
    "avoid repeating work:"
)

_PRUNED_TOOL_PLACEHOLDER = (
    "[Tool result truncated to save context space. "
    "Original length: {length}. Preview: {preview}...]"
)

_SUMMARY_REQUEST = """\
Please summarize the conversation above for context continuity. Include:
1. Main task/goal
2. Key constraints, decisions, and facts established
3. Progress: completed, in-progress, blocked
4. Important references (file paths, IDs, URLs, configs)
5. Current state and next steps
{focus_block}
Begin your summary with this prefix verbatim:
{prefix}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _estimate_message_chars(msg: Message) -> int:
    """Rough per-message character count — used only for tail-boundary splitting.

    The API gives us actual token counts after each call; this heuristic is
    only needed to decide how many messages belong in the protected tail before
    the next API call.
    """
    total = len(msg.content or "")
    if msg.tool_calls:
        total += len(json.dumps(msg.tool_calls))
    return total


def _take_tail_by_chars(messages: list[Message], char_budget: int) -> list[Message]:
    """Return the longest suffix of *messages* whose total char count ≤ char_budget."""
    accumulated = 0
    cutoff = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        accumulated += _estimate_message_chars(messages[i])
        if accumulated > char_budget:
            cutoff = i + 1
            break
    else:
        cutoff = 0  # everything fits
    return messages[cutoff:]


def _prune_tool_results(messages: list[Message], max_chars: int) -> list[Message]:
    """Replace large tool-result contents with a placeholder (in-place copy)."""
    out: list[Message] = []
    for msg in messages:
        if msg.role == "tool" and msg.content and len(msg.content) > max_chars:
            preview = msg.content[:200]
            pruned_content = _PRUNED_TOOL_PLACEHOLDER.format(
                length=len(msg.content), preview=preview
            )
            out.append(msg.model_copy(update={"content": pruned_content}))
        else:
            out.append(msg)
    return out


def _clean_orphan_tool_pairs(messages: list[Message]) -> list[Message]:
    """Ensure every tool_call in an assistant message has a matching tool result,
    and every tool result has a matching tool_call — removing or injecting as needed.

    Replicates the logic in state._inject_missing_tool_outputs and extends it to
    also remove dangling tool messages with no preceding tool_call.
    """
    # Pass 1: collect all tool_call IDs declared by assistant messages.
    declared_ids: set[str] = set()
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict) and isinstance(tc.get("id"), str):
                    declared_ids.add(tc["id"])

    # Pass 2: remove tool messages whose tool_call_id was never declared.
    filtered: list[Message] = []
    for msg in messages:
        if msg.role == "tool" and msg.tool_call_id and msg.tool_call_id not in declared_ids:
            continue  # orphaned result — drop it
        filtered.append(msg)

    # Pass 3: inject missing tool results for any tool_call without a result.
    out: list[Message] = []
    i = 0
    n = len(filtered)
    while i < n:
        m = filtered[i]
        out.append(m)
        if m.role == "assistant" and m.tool_calls:
            needed: list[str] = []
            for tc in m.tool_calls:
                if isinstance(tc, dict) and isinstance(tc.get("id"), str):
                    needed.append(tc["id"])
            have: set[str] = set()
            i += 1
            while i < n and filtered[i].role == "tool":
                tm = filtered[i]
                out.append(tm)
                if tm.tool_call_id:
                    have.add(tm.tool_call_id)
                i += 1
            for tid in needed:
                if tid not in have:
                    out.append(
                        Message(
                            role="tool",
                            content="[Tool result unavailable after context compaction; retry if still needed.]",
                            tool_call_id=tid,
                            name=None,
                        )
                    )
            continue
        i += 1
    return out


def _enforce_role_alternation(messages: list[Message]) -> list[Message]:
    """Insert minimal bridge messages to maintain user/assistant alternation.

    Provider APIs reject consecutive same-role messages (excluding tool
    messages which must follow an assistant with tool_calls).
    """
    if not messages:
        return messages

    out: list[Message] = [messages[0]]
    for msg in messages[1:]:
        prev = out[-1]
        prev_role = prev.role if prev.role != "tool" else "assistant"
        curr_role = msg.role if msg.role != "tool" else "assistant"

        if prev_role == curr_role == "user":
            out.append(Message(role="assistant", content="[Acknowledged]"))
        elif prev_role == curr_role == "assistant":
            out.append(Message(role="user", content="[Continuing]"))

        out.append(msg)
    return out


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    compacted_history: list[Message]
    original_tokens: int          # actual tokens_used from budget before compaction
    # char/4 estimate; real count known after next API call
    compacted_token_estimate: int
    compaction_triggered: bool
    summary_text: str | None = field(default=None)


# ---------------------------------------------------------------------------
# ContextCompactor
# ---------------------------------------------------------------------------


class ContextCompactor:
    """Compresses agent conversation history using the head/middle/tail algorithm.

    Threshold and sizing are read from environment variables at init time so
    operators can tune without code changes:
      PROXI_COMPACTION_THRESHOLD      float (default )
      PROXI_COMPACTION_HEAD_MESSAGES  int   (default 3)
      PROXI_COMPACTION_TAIL_TOKENS    int   (default 20000)
      PROXI_TOOL_RESULT_PRUNE_CHARS   int   (default 200)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        context_window: int = 128_000,
        compaction_threshold: float | None = None,
        head_messages: int | None = None,
        tail_tokens: int | None = None,
        tool_result_prune_chars: int | None = None,
        max_passes: int = 3,
        system_prompt: str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.context_window = context_window
        self.compaction_threshold = (
            compaction_threshold
            if compaction_threshold is not None
            else float(
                os.getenv(
                    "PROXI_COMPACTION_THRESHOLD",
                    str(DEFAULT_COMPACTION_THRESHOLD),
                )
            )
        )
        self.head_messages = (
            head_messages
            if head_messages is not None
            else int(os.getenv("PROXI_COMPACTION_HEAD_MESSAGES", "3"))
        )
        self.tail_tokens = (
            tail_tokens
            if tail_tokens is not None
            else int(os.getenv("PROXI_COMPACTION_TAIL_TOKENS", "20000"))
        )
        self.tool_result_prune_chars = (
            tool_result_prune_chars
            if tool_result_prune_chars is not None
            else int(os.getenv("PROXI_TOOL_RESULT_PRUNE_CHARS", "200"))
        )
        self.max_passes = max_passes
        # System prompt stored here so the loop doesn't need to pass it each call.
        # Updated by AgentLoop after each PromptBuilder cache refresh.
        self.system_prompt = system_prompt

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def maybe_compact(
        self,
        state: AgentState,
        current_tokens: int,
        focus: str | None = None,
    ) -> CompactionResult:
        """Compact only if current_tokens exceeds the configured threshold.

        current_tokens should be budget.tokens_used (the actual token count
        returned by the last API call, not an estimate).
        """
        threshold = int(self.context_window * self.compaction_threshold)
        if current_tokens < threshold:
            return CompactionResult(
                compacted_history=state.history,
                original_tokens=current_tokens,
                compacted_token_estimate=current_tokens,
                compaction_triggered=False,
            )

        return await self._run_passes(state, current_tokens=current_tokens, focus=focus)

    async def force_compact(
        self,
        state: AgentState,
        current_tokens: int = 0,
        focus: str | None = None,
    ) -> CompactionResult:
        """Compact regardless of current token count (e.g. manual /compact or reactive)."""
        return await self._run_passes(state, current_tokens=current_tokens, focus=focus)

    # ------------------------------------------------------------------
    # Internal: multi-pass driver
    # ------------------------------------------------------------------

    async def _run_passes(
        self,
        state: AgentState,
        current_tokens: int,
        focus: str | None,
    ) -> CompactionResult:
        original_tokens = current_tokens
        history = list(state.history)
        original_len = len(history)
        summary_text: str | None = None

        for _pass in range(self.max_passes):
            prev_len = len(history)
            history, summary_text = await self._compact_one_pass(history, focus=focus)
            if len(history) >= prev_len:
                break  # no progress — stop

        actually_compacted = len(
            history) < original_len or summary_text is not None

        if not actually_compacted:
            logger.info(
                "compaction_skipped_too_short",
                history_messages=original_len,
                head_messages=self.head_messages,
                tail_tokens=self.tail_tokens,
            )
            return CompactionResult(
                compacted_history=state.history,
                original_tokens=original_tokens,
                compacted_token_estimate=original_tokens,
                compaction_triggered=False,
                summary_text=None,
            )

        # Persist compacted history first — BEFORE injecting workspace context.
        # Workspace context injection is in-memory only (not written to history.jsonl)
        # so the agent can reference current todos/plan without persisting them.
        state.rewrite_history(history)
        state.total_tokens = 0  # reset; real count will come from next API call
        if state.turns:
            # Clear stale pre-compaction context snapshot so retries do not
            # immediately re-trigger compaction from an old turn value.
            state.turns[-1].tokens_used = 0

        # Step 7 — re-inject workspace todos/plan in-memory only (not written to jsonl)
        history_with_context = self._inject_workspace_context_from_state(
            history, state)
        if history_with_context is not history:
            state.history = list(history_with_context)

        estimate = sum(_estimate_message_chars(m) // 4 for m in history)

        logger.info(
            "compaction_complete",
            original_tokens=original_tokens,
            history_messages=len(history),
            estimated_tokens=estimate,
        )

        return CompactionResult(
            compacted_history=history_with_context,
            original_tokens=original_tokens,
            compacted_token_estimate=estimate,
            compaction_triggered=True,
            summary_text=summary_text,
        )

    # ------------------------------------------------------------------
    # Internal: single pass
    # ------------------------------------------------------------------

    async def _compact_one_pass(
        self,
        history: list[Message],
        focus: str | None,
    ) -> tuple[list[Message], str | None]:
        """Run one head/middle/tail compaction pass.

        Returns (compacted_history, summary_text).
        If the history is too short to compact, returns it unchanged.
        """
        n = len(history)
        head_count = min(self.head_messages, n)

        # Step 1 — identify tail by char budget
        tail_char_budget = self.tail_tokens * 4
        tail = _take_tail_by_chars(history[head_count:], tail_char_budget)
        tail_count = len(tail)

        middle_start = head_count
        middle_end = n - tail_count

        # Nothing to compress if middle is empty
        if middle_end <= middle_start:
            logger.debug("compaction_skipped_short_history", messages=n)
            return history, None

        head = history[:middle_start]
        middle = history[middle_start:middle_end]

        # Step 2 — prune large tool results in middle (cheap, no LLM call)
        middle_pruned = _prune_tool_results(
            middle, self.tool_result_prune_chars)

        # Step 3 — build summary request and call LLM (cache-safe fork)
        summary_text = await self._summarize(head, middle_pruned, focus)

        # Step 4 — assemble: head + summary_message + tail
        summary_msg = Message(role="user", content=summary_text)
        compacted = list(head) + [summary_msg] + list(tail)

        # Step 5 — clean up orphaned tool pairs
        compacted = _clean_orphan_tool_pairs(compacted)

        # Step 6 — enforce role alternation
        compacted = _enforce_role_alternation(compacted)

        return compacted, summary_text

    # ------------------------------------------------------------------
    # LLM summarization (cache-safe fork)
    # ------------------------------------------------------------------

    async def _summarize(
        self,
        head: list[Message],
        middle: list[Message],
        focus: str | None,
    ) -> str:
        """Call the LLM to summarize the middle turns.

        Uses head + middle as the conversation prefix (same bytes as the
        parent session's last request) so the provider's prompt cache is
        reused. Only the summary_request message at the end is new tokens.
        """
        focus_block = ""
        if focus:
            focus_block = (
                f"\nAdditional focus: {focus}\n"
                "Pay special attention to the above when deciding what to preserve in the summary.\n"
            )

        summary_request_content = _SUMMARY_REQUEST.format(
            focus_block=focus_block,
            prefix=_SUMMARY_PREFIX,
        )
        summary_request = Message(role="user", content=summary_request_content)

        summarizer_messages = list(head) + list(middle) + [summary_request]

        response = await self.llm_client.generate(
            messages=summarizer_messages,
            system=self.system_prompt,
            session_id=None,  # don't pollute parent's OpenAI cache key
        )

        content = response.decision.payload.get("content") or ""
        if not content:
            # Fallback: no content in payload (e.g. tool_call decision)
            content = f"{_SUMMARY_PREFIX}\n\n[Summary unavailable — context was pruned.]"

        # Ensure the required prefix is present
        if _SUMMARY_PREFIX not in content:
            content = f"{_SUMMARY_PREFIX}\n\n{content}"

        return content

    # ------------------------------------------------------------------
    # Post-compaction workspace context injection
    # ------------------------------------------------------------------

    def _inject_workspace_context_from_state(
        self,
        messages: list[Message],
        state: AgentState,
    ) -> list[Message]:
        """Read todos/plan from disk and append a context message if non-empty."""
        if state.workspace is None:
            return messages

        parts: list[str] = []

        todos_path = state.workspace.todos_path
        if todos_path:
            try:
                todos = Path(todos_path).read_text(encoding="utf-8").strip()
                if todos:
                    parts.append(f"## Todos\n{todos}")
            except OSError:
                pass

        plan_path = state.workspace.active_plan_path or state.workspace.plan_path
        if plan_path:
            try:
                plan = Path(plan_path).read_text(encoding="utf-8").strip()
                if plan:
                    parts.append(f"## Plan\n{plan}")
            except OSError:
                pass

        if not parts:
            return messages

        context_content = "[Post-compaction context]\n\n" + "\n\n".join(parts)
        return messages + [Message(role="user", content=context_content)]
