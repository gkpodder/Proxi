"""Filesystem tools for file operations."""

import aiofiles

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.path_guard import PathGuard


class ReadFileTool(BaseTool):
    """Tool for reading files."""

    def __init__(self, guard: PathGuard | None = None) -> None:
        super().__init__(
            name="read_file",
            description=(
                "Read the contents of a file. "
                "Use offset and limit to read specific line ranges (1-based). "
                "When offset/limit are provided, output includes line numbers."
            ),
            parallel_safe=True,
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "1-based line number to start reading from (default: 1)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to return (default: all)",
                    },
                },
                "required": ["path"],
            },
        )
        self._guard = guard or PathGuard(None)

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        path_str = arguments.get("path")
        if not path_str or not isinstance(path_str, str):
            return ToolResult(success=False, output="", error="Path argument is required")

        resolved, err = self._guard.guard_result(path_str)
        if err:
            return err

        offset_raw = arguments.get("offset")
        limit_raw = arguments.get("limit")
        offset = int(offset_raw) if offset_raw is not None else None
        limit = int(limit_raw) if limit_raw is not None else None

        try:
            if not resolved.exists():
                return ToolResult(
                    success=False, output="", error=f"File not found: {path_str}"
                )

            async with aiofiles.open(resolved, "r") as f:
                content = await f.read()

            if offset is None and limit is None:
                return ToolResult(
                    success=True,
                    output=content,
                    metadata={"path": str(resolved), "size": len(content)},
                )

            # Line-range read: output with line numbers (cat -n style)
            all_lines = content.splitlines()
            total = len(all_lines)
            start = max(1, offset or 1)
            end = min(total, (start - 1) + limit) if limit is not None else total

            selected = all_lines[start - 1 : end]
            numbered = [f"{start + i}\t{line}" for i, line in enumerate(selected)]
            output = "\n".join(numbered)

            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "path": str(resolved),
                    "total_lines": total,
                    "returned_lines": len(selected),
                    "start_line": start,
                    "end_line": start + len(selected) - 1,
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error reading file: {e}")


class WriteFileTool(BaseTool):
    """Tool for writing files."""

    def __init__(self, guard: PathGuard | None = None) -> None:
        super().__init__(
            name="write_file",
            description="Write content to a file",
            parallel_safe=False,
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
        self._guard = guard or PathGuard(None)

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        path_str = arguments.get("path")
        content = arguments.get("content")

        if not path_str or not isinstance(path_str, str) or content is None:
            return ToolResult(
                success=False, output="", error="Path and content arguments are required"
            )

        resolved, err = self._guard.guard_result(path_str)
        if err:
            return err

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(resolved, "w") as f:
                await f.write(str(content))

            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(str(content))} bytes to {path_str}",
                metadata={"path": str(resolved), "size": len(str(content))},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error writing file: {e}")



class EditFileTool(BaseTool):
    """Precise file editing via exact string replacement.

    Finds old_string in the file exactly once (or all occurrences when
    replace_all=true) and replaces it with new_string.  Fails with a
    descriptive error when the match count is ambiguous.
    """

    def __init__(self, guard: PathGuard | None = None) -> None:
        super().__init__(
            name="edit_file",
            description=(
                "Edit a file by replacing an exact string with a new one. "
                "The old_string must appear exactly once unless replace_all=true. "
                "Use read_file first to get the exact content to match."
            ),
            parallel_safe=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to edit",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Exact string to find and replace",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement string",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences (default: false — requires exactly one match)",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        )
        self._guard = guard or PathGuard(None)

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        file_path = arguments.get("file_path")
        old_string = arguments.get("old_string")
        new_string = arguments.get("new_string")
        replace_all = bool(arguments.get("replace_all", False))

        if not file_path or not isinstance(file_path, str):
            return ToolResult(success=False, output="", error="file_path argument is required")
        if old_string is None or not isinstance(old_string, str):
            return ToolResult(success=False, output="", error="old_string argument is required")
        if new_string is None or not isinstance(new_string, str):
            return ToolResult(success=False, output="", error="new_string argument is required")

        resolved, err = self._guard.guard_result(file_path)
        if err:
            return err

        try:
            if not resolved.exists():
                return ToolResult(
                    success=False, output="", error=f"File not found: {file_path}"
                )

            async with aiofiles.open(resolved, "r") as f:
                content = await f.read()

            count = content.count(old_string)

            if count == 0:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"old_string not found in {file_path}. Use read_file to verify the exact content.",
                )

            if not replace_all and count > 1:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"old_string appears {count} times in {file_path}. "
                        "Provide more surrounding context to make it unique, "
                        "or set replace_all=true to replace all occurrences."
                    ),
                )

            new_content = content.replace(old_string, new_string, -1 if replace_all else 1)

            async with aiofiles.open(resolved, "w") as f:
                await f.write(new_content)

            replacements = count if replace_all else 1
            return ToolResult(
                success=True,
                output=f"Replaced {replacements} occurrence(s) in {file_path}",
                metadata={"path": str(resolved), "replacements": replacements},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error editing file: {e}")
