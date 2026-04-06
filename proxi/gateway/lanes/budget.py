"""Per-lane budget enforcement (turns, tokens, wall-clock timeout)."""

from __future__ import annotations

from dataclasses import dataclass

from proxi.llm.model_registry import DEFAULT_COMPACTION_THRESHOLD


class BudgetExceeded(RuntimeError):
    """Raised when a lane hits a configured limit."""


@dataclass
class LaneBudget:
    max_turns: int = 1000
    token_budget: int = 80000
    context_window: int = 128_000
    wall_clock_timeout: float = 300.0
    compaction_threshold: float = DEFAULT_COMPACTION_THRESHOLD

    turns_used: int = 0
    tokens_used: int = 0

    def should_compact(self) -> bool:
        """True when context is full enough to warrant proactive compaction."""
        return (
            self.context_window > 0
            and self.tokens_used >= int(self.context_window * self.compaction_threshold)
        )

    def check(self) -> None:
        if self.turns_used >= self.max_turns:
            raise BudgetExceeded(f"turn limit ({self.max_turns})")
        if self.tokens_used >= self.token_budget:
            raise BudgetExceeded(f"token budget ({self.token_budget})")

    def record_turn(self, context_tokens: int = 0) -> None:
        self.turns_used += 1
        self.tokens_used = context_tokens  # current context size, not accumulated
        self.check()

    def reset(self) -> None:
        self.turns_used = 0
        self.tokens_used = 0
