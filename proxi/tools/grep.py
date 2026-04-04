"""Grep tool — ripgrep when available, pure-Python fallback otherwise."""

import asyncio
import re
import shlex
import shutil
from pathlib import Path

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.path_guard import PathGuard

# Resolve the rg binary once at import time.
_RG_BIN: str | None = shutil.which("rg")


def _python_grep(
    pattern: str,
    search_path: Path,
    glob_filter: str | None,
    context: int,
    case_insensitive: bool,
    output_mode: str,
    max_results: int,
) -> tuple[bool, str]:
    """Pure-Python grep fallback using pathlib + re."""
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return False, f"Invalid regex pattern: {e}"

    # Collect files to search
    if search_path.is_file():
        files = [search_path]
    else:
        if glob_filter:
            files = list(search_path.rglob(glob_filter))
        else:
            files = [f for f in search_path.rglob("*") if f.is_file()]
        files.sort()

    lines_out: list[str] = []
    count_map: dict[str, int] = {}
    files_with_matches: list[str] = []
    truncated = False

    for fpath in files:
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except (OSError, IsADirectoryError):
            continue
        file_lines = text.splitlines()

        match_indices: list[int] = [
            i for i, line in enumerate(file_lines) if compiled.search(line)
        ]
        if not match_indices:
            continue

        rel = str(fpath.relative_to(search_path)) if search_path.is_dir() else str(fpath)
        files_with_matches.append(rel)
        count_map[rel] = len(match_indices)

        if output_mode in ("files", "count"):
            continue

        # content mode with optional context
        shown: set[int] = set()
        for mi in match_indices:
            start = max(0, mi - context)
            end = min(len(file_lines) - 1, mi + context)
            for i in range(start, end + 1):
                shown.add(i)

        prev_i = -2
        for i in sorted(shown):
            if i != prev_i + 1 and prev_i >= 0:
                lines_out.append("--")
            prefix = ">" if i in set(match_indices) else " "
            lines_out.append(f"{rel}:{i + 1}{prefix}{file_lines[i]}")
            prev_i = i
            if len(lines_out) >= max_results:
                truncated = True
                break
        if truncated:
            break

    if not files_with_matches:
        return True, "(no matches)"

    if output_mode == "files":
        output = "\n".join(files_with_matches[:max_results])
        if len(files_with_matches) > max_results:
            output += f"\n... (truncated to {max_results} files)"
        return True, output

    if output_mode == "count":
        output_lines = [f"{path}: {cnt}" for path, cnt in list(count_map.items())[:max_results]]
        return True, "\n".join(output_lines)

    output = "\n".join(lines_out[:max_results])
    if truncated:
        output += f"\n... (output truncated to {max_results} lines)"
    return True, output


class GrepTool(BaseTool):
    """Search file contents using ripgrep (rg) or pure-Python regex fallback.

    Fast regex search across files. Useful for finding code patterns,
    function definitions, TODO comments, imports, and more.
    """

    def __init__(self, guard: PathGuard | None = None) -> None:
        super().__init__(
            name="grep",
            description=(
                "Search file contents using regex. "
                "Supports file glob filters and context lines. "
                "output_mode='files' returns only matching file paths; "
                "'count' returns match counts per file; "
                "'content' (default) returns matching lines with line numbers. "
                "Several independent searches (different paths or patterns) should be multiple grep "
                "calls in the same assistant turn, not one search per turn."
            ),
            parallel_safe=True,
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex or literal pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search (defaults to working directory)",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File filter glob pattern (e.g. '*.py', '**/*.ts')",
                    },
                    "context": {
                        "type": "integer",
                        "description": "Lines of context before and after each match",
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "Case-insensitive search",
                    },
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files", "count"],
                        "description": "Output format: 'content' (default), 'files', or 'count'",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum output lines to return (default: 200)",
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
        glob_pattern = arguments.get("glob")
        context = arguments.get("context")
        case_insensitive = bool(arguments.get("case_insensitive", False))
        output_mode = str(arguments.get("output_mode", "content"))
        max_results = int(arguments.get("max_results") or 200)
        context_int = int(context) if isinstance(context, int) and context > 0 else 0

        base = self._guard.base_dir or Path.cwd()

        if path_str:
            resolved, err = self._guard.guard_result(path_str)
            if err:
                return err
            search_path = resolved
        else:
            search_path = base

        if _RG_BIN:
            return await self._rg_grep(
                pattern, search_path, base, glob_pattern, context_int,
                case_insensitive, output_mode, max_results,
            )

        # Python fallback
        success, output = await asyncio.to_thread(
            _python_grep,
            pattern, search_path,
            str(glob_pattern) if glob_pattern else None,
            context_int, case_insensitive, output_mode, max_results,
        )
        return ToolResult(success=success, output=output, metadata={})

    async def _rg_grep(
        self,
        pattern: str,
        search_path: Path,
        base: Path,
        glob_pattern: object,
        context: int,
        case_insensitive: bool,
        output_mode: str,
        max_results: int,
    ) -> ToolResult:
        assert _RG_BIN is not None
        cmd: list[str] = [_RG_BIN, "--no-heading"]

        if output_mode == "files":
            cmd.append("--files-with-matches")
        elif output_mode == "count":
            cmd.append("--count")
        else:
            cmd.append("--line-number")

        if case_insensitive:
            cmd.append("--ignore-case")

        if glob_pattern and isinstance(glob_pattern, str):
            cmd.extend(["--glob", glob_pattern])

        if context > 0:
            cmd.extend(["--context", str(context)])

        cmd.extend(["--", pattern, str(search_path)])

        shell_cmd = shlex.join(cmd)
        try:
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(base),
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            return ToolResult(success=False, output="", error="grep timed out after 30 seconds")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"grep error: {e}")

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        if process.returncode == 2:
            return ToolResult(
                success=False, output="", error=stderr_text.strip() or "ripgrep error"
            )

        if not stdout_text.strip():
            return ToolResult(success=True, output="(no matches)", metadata={"match_count": 0})

        lines = stdout_text.splitlines()
        truncated = False
        if len(lines) > max_results:
            lines = lines[:max_results]
            truncated = True

        output = "\n".join(lines)
        if truncated:
            output += f"\n... (output truncated to {max_results} lines)"

        return ToolResult(
            success=True,
            output=output,
            metadata={"match_count": len(lines), "truncated": truncated},
        )
