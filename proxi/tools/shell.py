"""Shell tools for executing commands."""

import asyncio
from pathlib import Path

from proxi.tools.base import BaseTool, ToolResult


class ExecuteCommandTool(BaseTool):
    """Tool for executing shell commands."""

    def __init__(self, working_directory: Path | None = None):
        """Initialize the execute command tool."""
        super().__init__(
            name="execute_command",
            description="Execute a shell command and return the output",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 30)",
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
        )
        self.working_directory = working_directory or Path.cwd()

    async def execute(self, arguments: dict[str, str | int]) -> ToolResult:
        """Execute the shell command."""
        command = arguments.get("command")
        timeout = arguments.get("timeout", 30)

        if not command or not isinstance(command, str):
            return ToolResult(
                success=False,
                output="",
                error="Command argument is required and must be a string",
            )

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_directory,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(timeout)
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

            if return_code != 0:
                return ToolResult(
                    success=False,
                    output=stdout_text,
                    error=f"Command failed with exit code {return_code}\n{stderr_text}",
                    metadata={"return_code": return_code},
                )

            output = stdout_text if stdout_text else "(no output)"
            if stderr_text:
                output += f"\n[stderr]\n{stderr_text}"

            return ToolResult(
                success=True,
                output=output,
                metadata={"return_code": return_code, "command": command},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error executing command: {str(e)}",
            )
