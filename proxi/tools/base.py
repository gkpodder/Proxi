"""Base tool interface."""

from typing import Annotated, Any, Protocol

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Result from tool execution."""

    success: Annotated[bool, Field(
        description="Whether the tool execution succeeded")]
    output: Annotated[str, Field(description="Tool output")]
    error: Annotated[str | None, Field(
        default=None, description="Error message if failed")]
    metadata: Annotated[dict[str, Any], Field(
        default_factory=dict, description="Additional metadata")]


class Tool(Protocol):
    """Protocol for tools."""

    name: str
    description: str
    parameters_schema: dict[str, Any]

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """
        Execute the tool with given arguments.

        Args:
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        ...


class BaseTool:
    """Base implementation for tools."""

    defer_loading: bool = False
    """Set to True on a subclass to opt into deferred (on-demand) loading.

    Deferred tools are hidden from the LLM's tool list at startup and are
    only exposed after the LLM calls ``search_tools``.  Subclasses override
    this at the class level; it can also be set per-instance via the
    ``defer_loading`` kwarg to ``__init__``.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        *,
        parallel_safe: bool = False,
        defer_loading: bool | None = None,
    ):
        """Initialize the tool."""
        self.name = name
        self.description = description
        self.parameters_schema = parameters_schema
        self.parallel_safe = parallel_safe
        if defer_loading is not None:
            self.defer_loading = defer_loading

    def to_spec(self) -> dict[str, Any]:
        """Convert to tool specification."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }
