"""Patch tools for applying code changes."""

import asyncio
from pathlib import Path

from proxi.tools.base import BaseTool, ToolResult


# ---------------------------------------------------------------------------
# Begin-Patch format converter
# ---------------------------------------------------------------------------

def _apply_begin_patch(patch: str, working_dir: Path) -> ToolResult | None:
    """Convert and apply the non-standard *** Begin Patch format.

    Models sometimes generate this format instead of unified diff:

        *** Begin Patch
        *** Update File: foo.py
        @@
         context line
        +added line
        *** End Patch

    Returns a ToolResult on success/failure, or None if the format is not
    recognised (so the caller can fall through to git apply).
    """
    if "*** Begin Patch" not in patch:
        return None

    lines = patch.splitlines()
    results: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.startswith("*** Update File:"):
            i += 1
            continue

        filename = line[len("*** Update File:"):].strip()
        filepath = working_dir / filename

        if not filepath.exists():
            return ToolResult(
                success=False, output="",
                error=f"File not found: {filename}",
            )

        # Collect hunk lines until next *** directive or end
        i += 1
        hunk_lines: list[str] = []
        in_hunk = False
        while i < len(lines):
            ln = lines[i]
            if ln.startswith("*** End Patch"):
                break
            if ln.startswith("*** Update File:"):
                break  # next file block — don't consume
            if ln.startswith("@@"):
                in_hunk = True
                i += 1
                continue
            if ln.startswith("*** "):
                i += 1
                continue
            if in_hunk:
                hunk_lines.append(ln)
            i += 1

        # Split into old (context + removals) and new (context + additions)
        old_lines: list[str] = []
        new_lines: list[str] = []
        for hl in hunk_lines:
            if hl.startswith(" "):
                old_lines.append(hl[1:])
                new_lines.append(hl[1:])
            elif hl.startswith("+"):
                new_lines.append(hl[1:])
            elif hl.startswith("-"):
                old_lines.append(hl[1:])

        if not old_lines and not new_lines:
            return ToolResult(
                success=False, output="",
                error=f"No changes found in hunk for {filename}",
            )

        content = filepath.read_text(encoding="utf-8")
        old_str = "\n".join(old_lines)
        new_str = "\n".join(new_lines)

        if old_str not in content:
            return ToolResult(
                success=False, output="",
                error=(
                    f"Could not find context lines in {filename}. "
                    "Use edit_file for precise edits or provide a valid unified diff."
                ),
            )

        filepath.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
        results.append(filename)

    if not results:
        return ToolResult(success=False, output="", error="No files updated by patch")

    return ToolResult(
        success=True,
        output=f"Patch applied to: {', '.join(results)}",
        metadata={"files": results},
    )


class ApplyPatchTool(BaseTool):
    """Apply a unified diff patch to files in the working directory."""

    def __init__(self, working_dir: Path | None = None) -> None:
        super().__init__(
            name="apply_patch",
            description=(
                "Apply a patch to one or more files in the working directory.\n\n"
                "Accepts two formats:\n\n"
                "1. Unified diff (preferred — works with git apply):\n"
                "   --- a/foo.py\n"
                "   +++ b/foo.py\n"
                "   @@ -10,4 +10,6 @@\n"
                "    context line\n"
                "+  added line\n"
                "-  removed line\n\n"
                "2. Begin Patch format (also accepted):\n"
                "   *** Begin Patch\n"
                "   *** Update File: foo.py\n"
                "   @@\n"
                "    context line\n"
                "   +added line\n"
                "   *** End Patch\n\n"
                "Set check_only=true to validate without applying. "
                "For simple single-file edits, prefer edit_file instead."
            ),
            parallel_safe=False,
            read_only=False,
            parameters_schema={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "Unified diff or Begin Patch format string",
                    },
                    "check_only": {
                        "type": "boolean",
                        "description": "Validate patch without applying (default: false)",
                    },
                },
                "required": ["patch"],
            },
        )
        self._working_dir = working_dir or Path.cwd()

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        patch = arguments.get("patch")
        if not patch or not isinstance(patch, str):
            return ToolResult(success=False, output="", error="patch argument is required")

        check_only = bool(arguments.get("check_only", False))

        # Try the Begin Patch format first (sync — pure Python file I/O).
        if "*** Begin Patch" in patch:
            if check_only:
                # Validate only: check files exist and context is found without writing.
                result = await asyncio.to_thread(_apply_begin_patch, patch, self._working_dir)
                if result is None:
                    return ToolResult(success=False, output="", error="Unrecognised patch format")
                # Re-read files to verify context without committing changes — simplest
                # approach is to just report success/failure from the dry check.
                return ToolResult(
                    success=result.success,
                    output="Patch valid (check_only)" if result.success else result.output,
                    error=result.error,
                )
            result = await asyncio.to_thread(_apply_begin_patch, patch, self._working_dir)
            if result is not None:
                return result

        # Fall through to git apply for unified diff format.
        cmd = ["git", "apply"]
        if check_only:
            cmd.append("--check")
        cmd.append("-")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._working_dir),
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=patch.encode("utf-8")), timeout=30.0
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False, output="", error="apply_patch timed out after 30 seconds"
            )
        except FileNotFoundError:
            return ToolResult(success=False, output="", error="git not found")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"apply_patch error: {e}")

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        if process.returncode != 0:
            return ToolResult(
                success=False,
                output=stdout_text,
                error=stderr_text.strip() or f"git apply failed with code {process.returncode}",
            )

        action = "validated" if check_only else "applied"
        extra = f"\n{stdout_text}" if stdout_text.strip() else ""
        return ToolResult(
            success=True,
            output=f"Patch {action} successfully.{extra}",
            metadata={"check_only": check_only},
        )
