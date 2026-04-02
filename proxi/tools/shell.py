"""Shell/code execution tool."""

import asyncio
import re
import shlex
import shutil
import sys
from pathlib import Path

from proxi.tools.base import BaseTool, ToolResult
from proxi.tools.path_guard import PathGuard

# ---------------------------------------------------------------------------
# Platform shell detection
# ---------------------------------------------------------------------------
def _detect_shell() -> tuple[str, bool]:
    """Return (shell_executable, supports_stdin_script).

    On Windows: prefer PowerShell Core (pwsh), fall back to Windows PowerShell
    (powershell), last resort cmd.exe.  cmd.exe does not support reading a
    script from stdin, so we signal that with supports_stdin_script=False.

    On Unix/macOS: use bash (always available in a dev environment).
    """
    if sys.platform == "win32":
        for candidate in ("pwsh", "powershell"):
            found = shutil.which(candidate)
            if found:
                return found, True  # pwsh/powershell accept -Command -
        return "cmd.exe", False
    return "bash", True


_SHELL, _SHELL_STDIN = _detect_shell()
_IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------------------
# bash -c "..." unwrapper (Unix only — no-op on Windows)
# ---------------------------------------------------------------------------
_BASH_WRAPPER_RE = re.compile(r"^\s*bash\s+(-\S+)\s+", re.DOTALL)


def _unwrap_bash_c(command: str) -> str:
    """Strip a `bash -c '...'` / `bash -lc '...'` wrapper (Unix only).

    Models frequently wrap scripts in ``bash -lc "..."`` which breaks heredocs
    because heredocs are not processed inside double-quoted strings.  When we
    detect this pattern, we extract the inner script and run it directly (our
    executor already runs under bash via stdin).
    """
    if _IS_WINDOWS:
        return command
    m = _BASH_WRAPPER_RE.match(command)
    if not m or "c" not in m.group(1):
        return command
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command
    if not tokens or tokens[0] != "bash":
        return command
    for i, tok in enumerate(tokens[1:], 1):
        if re.match(r"^-[a-zA-Z]*c[a-zA-Z]*$", tok):
            if i + 1 < len(tokens):
                return tokens[i + 1]
            break
    return command


class ExecuteCodeTool(BaseTool):
    """Execute a shell command or code snippet.

    Runs inside the configured working directory.  When a PathGuard is set,
    any explicit working_directory overrides provided by the caller are
    validated against the guard before execution.

    Shell used:
      - Unix/macOS: bash (script passed via stdin)
      - Windows:    pwsh / powershell (script via stdin) or cmd.exe (via /C flag)
    """

    def __init__(
        self,
        working_directory: Path | None = None,
        guard: PathGuard | None = None,
    ) -> None:
        shell_hint = "PowerShell" if _IS_WINDOWS else "bash"
        super().__init__(
            name="execute_code",
            description=(
                f"Execute a shell command and return stdout/stderr. "
                f"Runs in the configured working directory using {shell_hint}. "
                "Use for running scripts, compiling code, running tests, "
                "installing packages, and inspecting command output.\n\n"
                "IMPORTANT USAGE RULES:\n"
                "- Write the command directly — do NOT wrap it in `bash -c '...'` or `bash -lc '...'`. "
                "The command already runs in the shell.\n"
                "- To create or overwrite files with content, use the `write_file` tool instead of "
                "shell heredocs (`<< EOF`). Heredocs break inside shell commands passed to this tool.\n"
                "- Multiline scripts work fine: use semicolons or newlines to chain commands.\n\n"
                "OUTPUT SIZE: Keep output lean by default — prefer compact flags and pipe verbose "
                "commands through `| tail -n 50` or `| head -n 50`. "
                "Examples: `pytest -q --tb=short` instead of `pytest -v`, "
                "`git log --oneline -10` instead of `git log`, `npm install --silent`. "
                "If truncated output wasn't enough, write a more targeted command "
                "(narrower pattern, specific file path) rather than re-running with more output."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute. Run directly — do not wrap in bash -c.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 60)",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
        )
        self._guard = guard
        self.working_directory = working_directory or (
            guard.base_dir if guard and guard.base_dir else Path.cwd()
        )

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        command = arguments.get("command")
        timeout = arguments.get("timeout") or 60

        if not command or not isinstance(command, str):
            return ToolResult(
                success=False,
                output="",
                error="command argument is required and must be a string",
            )

        # Strip any `bash -c "..."` / `bash -lc "..."` wrapper (Unix only).
        command = _unwrap_bash_c(command)

        if not self.working_directory.exists():
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Working directory does not exist: {self.working_directory}. "
                    "Create it first or update the agent's working_dir setting."
                ),
            )

        try:
            if _SHELL_STDIN:
                # bash / pwsh: pass script via stdin to avoid all quoting issues.
                if _IS_WINDOWS:
                    proc_args = [_SHELL, "-Command", "-"]
                else:
                    proc_args = [_SHELL]
                process = await asyncio.create_subprocess_exec(
                    *proc_args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.working_directory,
                )
                stdin_bytes: bytes | None = command.encode()
            else:
                # cmd.exe fallback: pass command via /C flag.
                process = await asyncio.create_subprocess_exec(
                    _SHELL, "/C", command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.working_directory,
                )
                stdin_bytes = None

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=stdin_bytes), timeout=float(timeout)
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Command timed out after {timeout} seconds",
                )

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            return_code = process.returncode

            # Truncate large outputs to prevent context flooding.
            _MAX_OUTPUT = 15_000
            truncated = False
            if len(stdout_text) > _MAX_OUTPUT:
                stdout_text = stdout_text[:_MAX_OUTPUT]
                truncated = True

            if return_code != 0:
                return ToolResult(
                    success=False,
                    output=stdout_text + ("\n[output truncated]" if truncated else ""),
                    error=f"Command failed with exit code {return_code}\n{stderr_text}",
                    metadata={"return_code": return_code},
                )

            output = stdout_text if stdout_text else "(no output)"
            if truncated:
                output += "\n[output truncated at 50 000 chars]"
            if stderr_text:
                output += f"\n[stderr]\n{stderr_text}"

            return ToolResult(
                success=True,
                output=output,
                metadata={"return_code": return_code, "command": command},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Error executing command: {e}")


# Backward-compatibility alias
ExecuteCommandTool = ExecuteCodeTool
