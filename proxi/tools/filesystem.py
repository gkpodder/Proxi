"""Filesystem tools for file operations."""

import aiofiles
from pathlib import Path

from proxi.tools.base import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    """Tool for reading files."""

    def __init__(self):
        """Initialize the read file tool."""
        super().__init__(
            name="read_file",
            description="Read the contents of a file",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    },
                },
                "required": ["path"],
            },
        )

    async def execute(self, arguments: dict[str, str]) -> ToolResult:
        """Execute the read file operation."""
        path_str = arguments.get("path")
        if not path_str:
            return ToolResult(
                success=False,
                output="",
                error="Path argument is required",
            )

        try:
            path = Path(path_str)
            if not path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {path_str}",
                )

            async with aiofiles.open(path, "r") as f:
                content = await f.read()

            return ToolResult(
                success=True,
                output=content,
                metadata={"path": str(path), "size": len(content)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error reading file: {str(e)}",
            )


class WriteFileTool(BaseTool):
    """Tool for writing files."""

    def __init__(self):
        """Initialize the write file tool."""
        super().__init__(
            name="write_file",
            description="Write content to a file",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        )

    async def execute(self, arguments: dict[str, str]) -> ToolResult:
        """Execute the write file operation."""
        path_str = arguments.get("path")
        content = arguments.get("content")

        if not path_str or content is None:
            return ToolResult(
                success=False,
                output="",
                error="Path and content arguments are required",
            )

        try:
            path = Path(path_str)
            path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(path, "w") as f:
                await f.write(content)

            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} bytes to {path_str}",
                metadata={"path": str(path), "size": len(content)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error writing file: {str(e)}",
            )


class ListDirectoryTool(BaseTool):
    """Tool for listing directory contents."""

    def __init__(self):
        """Initialize the list directory tool."""
        super().__init__(
            name="list_directory",
            description="List contents of a directory",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the directory to list",
                    },
                },
                "required": ["path"],
            },
        )

    async def execute(self, arguments: dict[str, str]) -> ToolResult:
        """Execute the list directory operation."""
        path_str = arguments.get("path")
        if not path_str:
            return ToolResult(
                success=False,
                output="",
                error="Path argument is required",
            )

        try:
            path = Path(path_str)
            if not path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory not found: {path_str}",
                )

            if not path.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path is not a directory: {path_str}",
                )

            items = []
            for item in sorted(path.iterdir()):
                item_type = "directory" if item.is_dir() else "file"
                items.append(f"{item_type}: {item.name}")

            output = "\n".join(items) if items else "Directory is empty"

            return ToolResult(
                success=True,
                output=output,
                metadata={"path": str(path), "count": len(items)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error listing directory: {str(e)}",
            )
