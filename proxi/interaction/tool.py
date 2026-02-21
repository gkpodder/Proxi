"""Tool definition for show_collaborative_form."""

import json

from pydantic import ValidationError

from proxi.interaction.models import FormRequest
from proxi.llm.schemas import ToolSpec


# Tool definition passed to the LLM via the chat completions API `tools` array.
def _build_tool_schema() -> dict:
    """Build the JSON schema for FormRequest, suitable for OpenAI function calling."""
    return FormRequest.model_json_schema()


SHOW_COLLABORATIVE_FORM_TOOL = {
    "type": "function",
    "function": {
        "name": "show_collaborative_form",
        "description": (
            "Present a structured form to the user to collect information needed before proceeding. "
            "Use this when you need specific inputs that would materially change your approach or output. "
            "Do NOT use for minor clarifications — use RESPOND for conversational follow-ups instead. "
            "'choice' and 'multiselect' types automatically include a free-text 'Other' option in the TUI — "
            "do not add it to the options array yourself."
        ),
        "parameters": _build_tool_schema(),
    },
}


def get_show_collaborative_form_spec() -> ToolSpec:
    """Return ToolSpec for registration in ToolRegistry."""
    fn = SHOW_COLLABORATIVE_FORM_TOOL["function"]
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
