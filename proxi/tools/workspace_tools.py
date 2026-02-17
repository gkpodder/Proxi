"""Workspace-scoped tools for managing plan/todos and reading the agent Soul."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from proxi.core.state import WorkspaceConfig
from proxi.tools.base import BaseTool, ToolResult


class ManagePlanTool(BaseTool):
    """Tool for reading or updating the current session plan.md."""

    def __init__(self, workspace: WorkspaceConfig):
        super().__init__(
            name="manage_plan",
            description=(
                "Read or update plan.md in the current session workspace. "
                "If 'content' is provided, it overwrites the file; otherwise "
                "the current contents are returned."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Optional full content to write into plan.md.",
                    },
                },
            },
        )
        self._workspace = workspace

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = Path(self._workspace.plan_path)
        content = arguments.get("content")

        try:
            if content is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(content), encoding="utf-8")
                return ToolResult(
                    success=True,
                    output="plan.md updated",
                    metadata={"path": str(path), "size": len(str(content))},
                    error=None,
                )

            # Read-only mode if content not provided
            if not path.exists():
                return ToolResult(
                    success=True,
                    output="",
                    metadata={"path": str(path), "size": 0},
                    error=None,
                )

            text = path.read_text(encoding="utf-8")
            return ToolResult(
                success=True,
                output=text,
                metadata={"path": str(path), "size": len(text)},
                error=None,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class ManageTodosTool(BaseTool):
    """Tool for managing the current session todos.md file."""

    def __init__(self, workspace: WorkspaceConfig):
        super().__init__(
            name="manage_todos",
            description=(
                "Read or update todos.md in the current session workspace. "
                "If 'content' is provided, it overwrites the file; otherwise "
                "the current contents are returned."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Optional full content to write into todos.md.",
                    },
                },
            },
        )
        self._workspace = workspace

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = Path(self._workspace.todos_path)
        content = arguments.get("content")

        try:
            if content is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(content), encoding="utf-8")
                return ToolResult(
                    success=True,
                    output="todos.md updated",
                    metadata={"path": str(path), "size": len(str(content))},
                    error=None,
                )

            # Read-only mode if content not provided
            if not path.exists():
                return ToolResult(
                    success=True,
                    output="",
                    metadata={"path": str(path), "size": 0},
                    error=None,
                )

            text = path.read_text(encoding="utf-8")
            return ToolResult(
                success=True,
                output=text,
                metadata={"path": str(path), "size": len(text)},
                error=None,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class ReadSoulTool(BaseTool):
    """Tool that allows the agent to read its own Soul.md."""

    def __init__(self, workspace: WorkspaceConfig):
        super().__init__(
            name="read_soul",
            description="Read the Soul.md file for the current agent.",
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )
        self._workspace = workspace

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:  # type: ignore[override]
        try:
            path = Path(self._workspace.soul_path)
            if not path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Soul.md not found at {path}",
                )
            text = path.read_text(encoding="utf-8")
            return ToolResult(
                success=True,
                output=text,
                metadata={"path": str(path), "size": len(text)},
                error=None,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )

