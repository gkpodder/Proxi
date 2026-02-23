"""Collaborative form interaction for structured user input collection."""

from proxi.interaction.models import (
    FormRequest,
    FormResponse,
    InteractionRecord,
    Question,
)
from proxi.interaction.tool import (
    SHOW_COLLABORATIVE_FORM_TOOL,
    get_show_collaborative_form_spec,
    parse_form_tool_call,
)

__all__ = [
    "FormRequest",
    "FormResponse",
    "InteractionRecord",
    "Question",
    "SHOW_COLLABORATIVE_FORM_TOOL",
    "get_show_collaborative_form_spec",
    "parse_form_tool_call",
]
