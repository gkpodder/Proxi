"""Glob tool for fast file pattern matching."""

from pathlib import Path

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.path_guard import PathGuard


class GlobTool(BaseTool):
    """Find files matching a glob pattern within the working directory."""

    def __init__(self, guard: PathGuard | None = None) -> None:
        super().__init__(
            name="glob",
            description=(
                "Find files matching a glob pattern. "
                "Supports patterns like '**/*.py', 'src/**/*.ts', '*.json'. "
                "Results are sorted by modification time (newest first)."
            ),
            parallel_safe=True,
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g. '**/*.py', 'src/**/*.ts')",
                    },
                    "path": {
                        "type": "string",
                        "description": "Base directory to search (defaults to working directory)",
                    },
                },
                "required": ["pattern"],
            },
        )
        self._guard = guard or PathGuard(None)

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        pattern = arguments.get("pattern")
        if not pattern or not isinstance(pattern, str):
            return ToolResult(success=False, output="", error="pattern argument is required")

        path_str = arguments.get("path")
        base = self._guard.base_dir or Path.cwd()

        if path_str:
            resolved, err = self._guard.guard_result(path_str)
            if err:
                return err
            search_root = resolved
        else:
            search_root = base

        if not search_root.exists():
            return ToolResult(
                success=False, output="", error=f"Path not found: {search_root}"
            )
        if not search_root.is_dir():
            return ToolResult(
                success=False, output="", error=f"Path is not a directory: {search_root}"
            )

        try:
            matches = list(search_root.glob(pattern))
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Glob error: {e}")

        if not matches:
            return ToolResult(success=True, output="(no matches)", metadata={"count": 0})

        lines = []
        for m in matches:
            try:
                lines.append(str(m.relative_to(search_root)))
            except ValueError:
                lines.append(str(m))

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={"count": len(lines), "base": str(search_root)},
        )
