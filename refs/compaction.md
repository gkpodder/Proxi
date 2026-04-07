# Context Compaction

This document describes how context compaction is currently implemented in Proxi, based on `proxi/core/compactor.py`.

## Table of Contents

- [Why Compaction Exists](#why-compaction-exists)
- [Component and Data Flow](#component-and-data-flow)
- [Triggering Modes](#triggering-modes)
- [Compaction Algorithm (Single Pass)](#compaction-algorithm-single-pass)
- [Multi-Pass Behavior](#multi-pass-behavior)
- [Post-Compaction State Updates](#post-compaction-state-updates)
- [Safety and Consistency Guarantees](#safety-and-consistency-guarantees)
- [Configuration and Tuning](#configuration-and-tuning)
- [Failure and Fallback Behavior](#failure-and-fallback-behavior)
- [Operational Notes](#operational-notes)

---

## Why Compaction Exists

Long-running sessions can exceed practical model context limits. Proxi's compactor reduces history size while preserving enough structure and recency for the agent to continue accurately.

Design goals:

- Preserve early intent and constraints (head).
- Preserve most recent actionable context (tail).
- Compress older middle turns into a durable summary.
- Keep message structure valid for provider APIs.

---

## Component and Data Flow

The compaction entrypoint is `ContextCompactor`, which works over `AgentState.history` (`list[Message]`) and uses `LLMClient` for summarization.

High-level flow:

```text
AgentState.history + current token usage
    -> maybe_compact(...) or force_compact(...)
    -> _run_passes(...)
        -> _compact_one_pass(...)
            -> _take_tail_by_chars(...)
            -> _prune_tool_results(...)
            -> _summarize(...)
            -> _clean_orphan_tool_pairs(...)
            -> _enforce_role_alternation(...)
    -> state.rewrite_history(...)
    -> optional in-memory workspace context injection (todos/plan)
```

`CompactionResult` returns:

- `compacted_history`
- `original_tokens`
- `compacted_token_estimate` (char-based estimate, not provider ground truth)
- `compaction_triggered`
- `summary_text` (if produced)

---

## Triggering Modes

### Automatic (`maybe_compact`)

Compaction is triggered when:

```text
current_tokens >= context_window * compaction_threshold
```

Where:

- `current_tokens` is expected to be the real `budget.tokens_used` from the last model call.
- `context_window` defaults to `128000`.
- `compaction_threshold` defaults from `DEFAULT_COMPACTION_THRESHOLD` (or `PROXI_COMPACTION_THRESHOLD`).

If below threshold, the original history is returned unchanged.

### Forced (`force_compact`)

Compaction runs regardless of token usage. This supports manual or reactive call-sites.

---

## Compaction Algorithm (Single Pass)

One pass in `_compact_one_pass(...)` performs:

1. **Choose protected head**
   - Keep first `head_messages` (default `3`).

2. **Choose protected tail**
   - Tail budget is `tail_tokens * 4` chars (default `20000 * 4`).
   - `_take_tail_by_chars(...)` walks backward to keep the longest suffix that fits budget.

3. **Define middle segment**
   - `middle = history[head_count : n - tail_count]`.
   - If middle is empty, compaction is skipped for this pass.

4. **Prune large tool results in middle**
   - `_prune_tool_results(...)` replaces oversized `tool` message content with a placeholder:
     - reports original length
     - includes a short preview
   - This reduces summary input size before LLM invocation.

5. **Summarize middle with cache-safe request shape**
   - `_summarize(head, middle_pruned, focus)` builds:
     - original `head`
     - pruned `middle`
     - a final summary request message
   - The summary prompt asks for:
     - main goal
     - constraints/decisions/facts
     - progress state
     - important references
     - current state and next steps
   - If `focus` is provided, it is injected as "Additional focus".
   - A fixed compaction prefix is required in output.

6. **Reassemble compacted history**
   - New sequence is:
     - `head`
     - one summary `Message(role="user", content=summary_text)`
     - protected `tail`

7. **Repair tool-call/result consistency**
   - `_clean_orphan_tool_pairs(...)`:
     - drops tool results with unknown `tool_call_id`
     - injects synthetic fallback tool results when assistant tool calls have no corresponding result

8. **Enforce role alternation**
   - `_enforce_role_alternation(...)` inserts minimal bridge messages if needed:
     - assistant `[Acknowledged]` between consecutive `user`
     - user `[Continuing]` between consecutive `assistant`
   - Tool role is normalized as assistant-adjacent for alternation checks.

---

## Multi-Pass Behavior

`_run_passes(...)` executes up to `max_passes` (default `3`):

- Runs single-pass compaction repeatedly.
- Stops early if no progress (`len(history)` does not decrease).
- Marks compaction as "actually compacted" if message count shrank or a summary exists.

If nothing meaningful changed, the compactor logs a skip event and returns the original state as untriggered.

---

## Post-Compaction State Updates

After successful compaction:

1. Persist compacted history with `state.rewrite_history(history)`.
2. Reset token counters:
   - `state.total_tokens = 0`
   - clear latest turn `tokens_used` if present.
3. Re-inject workspace context in memory only:
   - reads `todos.md` and active `plan.md` (if available)
   - appends one `[Post-compaction context]` user message containing those sections
   - **not written** to persisted `history.jsonl`.

This ensures durable history stays compact while the active in-memory context still includes current planning artifacts.

---

## Safety and Consistency Guarantees

Current invariants enforced by implementation:

- **Prefix guarantee:** summary text is forced to include the compaction preamble if the model omits it.
- **Tool integrity:** missing/dangling tool pairs are repaired or dropped.
- **Alternation validity:** user/assistant turn ordering is normalized to reduce provider API rejection risk.
- **Fallback summary content:** if summarizer response has empty content, a fallback marker summary is inserted.
- **Session cache isolation:** summarizer call uses `session_id=None` so it does not pollute parent OpenAI cache key.

---

## Configuration and Tuning

`ContextCompactor` can be configured by constructor args or env vars:

| Variable | Default | Effect |
|---|---|---|
| `PROXI_COMPACTION_THRESHOLD` | `DEFAULT_COMPACTION_THRESHOLD` | Fraction of context window that triggers automatic compaction |
| `PROXI_COMPACTION_HEAD_MESSAGES` | `3` | Number of early messages always preserved |
| `PROXI_COMPACTION_TAIL_TOKENS` | `20000` | Approximate recent context to preserve in tail |
| `PROXI_TOOL_RESULT_PRUNE_CHARS` | `200` | Max chars for middle tool outputs before placeholder truncation |

Other constructor knobs:

- `context_window` (default `128000`)
- `max_passes` (default `3`)
- `system_prompt` for summarizer LLM call

---

## Failure and Fallback Behavior

- If history is too short (no middle region), pass returns unchanged.
- If summarizer returns non-content payload, fallback summary text is used.
- If workspace todo/plan files cannot be read, injection is skipped silently.
- If compaction produces no reduction and no summary, operation is treated as skipped.

---

## Operational Notes

- Token reduction after compaction is estimated as `sum(message_chars // 4)`; real token usage is learned on the next provider call.
- Compaction summary is inserted as a `user` message by design, and downstream alternation repair ensures provider-compatible sequencing.
- Middle tool output pruning happens before summary generation to reduce summarization cost and avoid flooding summary context with large raw outputs.

