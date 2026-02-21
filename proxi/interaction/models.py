"""Pydantic models for collaborative form requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Question(BaseModel):
    """A single question in a collaborative form."""

    id: str = Field(
        description="Snake_case identifier. Used as the key in the answer dict."
    )
    type: Literal["choice", "multiselect", "yesno", "text"]
    question: str = Field(
        description="The question shown to the user. Plain language, no jargon."
    )
    options: list[str] | None = Field(
        default=None,
        description=(
            "Required for 'choice' and 'multiselect'. Do NOT include a custom/other option — "
            "the TUI appends 'Other (type your own)' automatically as the last choice."
        ),
    )
    placeholder: str | None = Field(
        default=None,
        description="Hint text displayed inside the input field for 'text' type questions."
    )
    hint: str | None = Field(
        default=None,
        description=(
            "A short 'why it matters' explanation shown below the question in the TUI. "
            "Helps users understand the implications of their choice. "
            "This is user-facing — use plain, accessible language."
        ),
    )
    required: bool = True
    show_if: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Conditional display rule evaluated by the TUI. "
            "Example: {'question_id': 'has_account', 'equals': True}. "
            "Question is hidden until the condition is met."
        ),
    )
    why: str = Field(
        description=(
            "Internal reasoning: why the agent needs this specific piece of information "
            "and how the answer will affect subsequent steps. "
            "Used by the Reflector — NOT shown to the user (use `hint` for user-facing context)."
        )
    )

    @model_validator(mode="after")
    def options_required_for_choice_types(self) -> "Question":
        if self.type in ("choice", "multiselect") and not self.options:
            raise ValueError(
                f"Question '{self.id}' is type '{self.type}' and must include an 'options' list."
            )
        if self.type in ("yesno", "text") and self.options:
            raise ValueError(
                f"Question '{self.id}' is type '{self.type}' and must not include 'options'."
            )
        return self


class FormRequest(BaseModel):
    """Request to present a collaborative form to the user."""

    goal: str = Field(
        description=(
            "One sentence: what the agent is trying to determine with this form. "
            "Used by the Reflector to evaluate whether the answers resolved the need."
        )
    )
    title: str | None = Field(
        default=None,
        description="Optional form title shown in the TUI header."
    )
    questions: list[Question] = Field(min_length=1, max_length=10)
    allow_skip: bool = Field(
        default=False,
        description=(
            "If true, the user can press Esc to cancel the form. "
            "The agent receives a cancellation signal as the tool result."
        ),
    )


class FormResponse(BaseModel):
    """Typed answers returned from the TUI after form completion."""

    answers: dict[str, Any]  # keyed by Question.id
    skipped: bool = False  # True if user pressed Esc and allow_skip was True
    form_goal: str  # echoed from FormRequest.goal for AgentState history


class InteractionRecord(BaseModel):
    """Persisted record of a complete form round-trip stored in AgentState."""

    timestamp: datetime
    form_request: FormRequest
    form_response: FormResponse
