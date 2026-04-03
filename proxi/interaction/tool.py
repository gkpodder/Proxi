"""Tool definition for ask_user_question."""

import json

from proxi.interaction.models import FormRequest
from proxi.llm.schemas import ToolSpec


def _build_tool_schema() -> dict:
    """Minimal hand-crafted schema for ask_user_question.

    Intentionally terse to minimise token usage.  Pydantic validation in
    parse_form_tool_call() enforces the full constraints at runtime.
    """
    return {
        "type": "object",
        "required": ["goal", "questions"],
        "additionalProperties": False,
        "properties": {
            "goal": {"type": "string", "description": "One sentence: what you need to determine."},
            "title": {"type": "string"},
            "allow_skip": {"type": "boolean", "default": False},
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "required": ["id", "type", "question"],
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "description": "snake_case answer key."},
                        "type": {
                            "type": "string",
                            "enum": ["choice", "multiselect", "yesno", "text"],
                        },
                        "question": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required for choice/multiselect. Omit for yesno/text.",
                        },
                        "placeholder": {"type": "string"},
                        "hint": {
                            "type": "string",
                            "description": "User-facing context shown below the question.",
                        },
                    },
                },
            },
        },
    }


ASK_USER_QUESTION_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_user_question",
        "description": (
            "Probe the user to clarify vague requirements, co-build a plan/spec, or gather details "
            "needed before acting. Use when: (1) the task is ambiguous and assumptions would risk a wrong result, "
            "(2) the user asks to be interviewed or wants to build a plan/spec together, "
            "(3) key details (dates, times, attendees, scope, preferences) are missing and cannot be inferred—including calendar/event setup. "
            "Do NOT use for simple yes/no clarifications—ask those conversationally with RESPOND. "
            "Prefer yesno/choice over text; keep questions minimal. "
            "For choice/multiselect, list real options only—Other is auto-appended; never add it yourself."
        ),
        "parameters": _build_tool_schema(),
    },
}


def get_ask_user_question_spec() -> ToolSpec:
    """Return ToolSpec for registration in ToolRegistry."""
    fn = ASK_USER_QUESTION_TOOL["function"]
    return ToolSpec(
        name=fn["name"],
        description=fn["description"],
        parameters=fn["parameters"],
    )


def parse_form_tool_call(tool_call_arguments: str) -> FormRequest:
    """
    Parse and validate the LLM's tool call arguments into a FormRequest.
    Raises ValidationError with structured messages if the schema is violated,
    which the loop returns to the LLM as a tool error for self-correction.
    """
    raw = json.loads(tool_call_arguments)
    return FormRequest.model_validate(raw)
