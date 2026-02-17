"""Schemas for LLM requests and responses."""

from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class DecisionType(str, Enum):
    """Type of decision made by the model."""

    RESPOND = "respond"
    TOOL_CALL = "tool_call"
    SUB_AGENT_CALL = "sub_agent_call"


class ToolSpec(BaseModel):
    """Specification for a tool available to the model."""

    name: Annotated[str, Field(description="Tool name")]
    description: Annotated[str, Field(description="Tool description")]
    parameters: Annotated[dict[str, Any], Field(description="JSON schema for tool parameters")]


class SubAgentSpec(BaseModel):
    """Specification for a sub-agent available to the model."""

    name: Annotated[str, Field(description="Sub-agent name")]
    description: Annotated[str, Field(description="Sub-agent description")]
    input_schema: Annotated[dict[str, Any], Field(description="JSON schema for input")]


class ToolCall(BaseModel):
    """A tool call request."""

    id: Annotated[str, Field(description="Unique tool call ID")]
    name: Annotated[str, Field(description="Tool name")]
    arguments: Annotated[dict[str, Any], Field(description="Tool arguments")]


class SubAgentCall(BaseModel):
    """A sub-agent call request."""

    agent: Annotated[str, Field(description="Sub-agent name")]
    task: Annotated[str, Field(description="Task description")]
    context_refs: Annotated[list[str] | dict[str, Any], Field(default_factory=list, description="Context references (list of IDs or dict of values)")]


class ModelDecision(BaseModel):
    """Decision made by the model."""

    type: Annotated[DecisionType, Field(description="Type of decision")]
    payload: Annotated[dict[str, Any], Field(description="Decision payload")]
    reasoning: Annotated[str | None, Field(default=None, description="Reasoning behind the decision")]

    @classmethod
    def respond(cls, content: str, reasoning: str | None = None) -> "ModelDecision":
        """Create a respond decision."""
        return cls(
            type=DecisionType.RESPOND,
            payload={"content": content},
            reasoning=reasoning,
        )

    @classmethod
    def tool_call(cls, tool_call: ToolCall, reasoning: str | None = None) -> "ModelDecision":
        """Create a tool call decision."""
        return cls(
            type=DecisionType.TOOL_CALL,
            payload={
                "id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            },
            reasoning=reasoning,
        )

    @classmethod
    def sub_agent_call(
        cls, agent_call: SubAgentCall, reasoning: str | None = None
    ) -> "ModelDecision":
        """Create a sub-agent call decision."""
        return cls(
            type=DecisionType.SUB_AGENT_CALL,
            payload={
                "agent": agent_call.agent,
                "task": agent_call.task,
                "context_refs": agent_call.context_refs,
            },
            reasoning=reasoning,
        )


class ModelResponse(BaseModel):
    """Complete response from the model."""

    decision: ModelDecision
    usage: Annotated[dict[str, Any], Field(description="Token usage (prompt_tokens, completion_tokens, total_tokens, optional prompt_tokens_details)")]
    finish_reason: Annotated[str | None, Field(default=None, description="Finish reason")]
