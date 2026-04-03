"""CLI-backed tools: fixed commands, structured args → CLI flags.

Pattern for adding a new CLI tool:
  1. Write a script under proxi/scripts/ with argparse subcommands or flags.
  2. Subclass CLITool, set command=[sys.executable, "-m", "proxi.scripts.<name>", ...].
  3. Append the new class to CLI_TOOLS at the bottom of this file.
  4. Adjust config/mcp.json cliTools.always_load if it should be live instead of deferred.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from proxi.tools.base import BaseTool, ToolResult

_MAX_OUTPUT = 15_000


class CLITool(BaseTool):
    """Base class for tools backed by a pre-configured CLI script.

    Subclasses define ``command`` in ``__init__``; the LLM never composes it.
    Structured arguments from the LLM are translated to ``--flag value`` CLI
    pairs by ``_build_argv``.  Subclasses can override ``_build_argv`` for
    non-standard argument layouts.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        command: list[str],
        *,
        timeout: int = 30,
        parallel_safe: bool = False,
        defer_loading: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            parallel_safe=parallel_safe,
            parameters_schema=parameters_schema,
        )
        self._command = command
        self._timeout = timeout
        self.defer_loading = defer_loading

    def _build_argv(self, arguments: dict[str, Any]) -> list[str]:
        """Translate ``{key: value}`` arguments to ``[--key, value]`` CLI flags.

        Rules:
        - ``None`` or ``False``  → skip (flag omitted)
        - ``True``               → ``--flag`` (bare flag, no value)
        - ``list``               → ``--flag val1 --flag val2`` (repeated)
        - everything else        → ``--flag str(value)``
        - underscores in keys    → hyphens (``temperature_unit`` → ``--temperature-unit``)
        """
        argv: list[str] = []
        for key, value in arguments.items():
            flag = f"--{key.replace('_', '-')}"
            if value is None or value is False:
                continue
            elif value is True:
                argv.append(flag)
            elif isinstance(value, list):
                for item in value:
                    argv.extend([flag, str(item)])
            else:
                argv.extend([flag, str(value)])
        return argv

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        argv = self._command + self._build_argv(arguments)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=float(self._timeout)
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Tool timed out after {self._timeout}s",
                )

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            rc = process.returncode

            truncated = len(out) > _MAX_OUTPUT
            if truncated:
                out = out[:_MAX_OUTPUT]

            if rc != 0:
                return ToolResult(
                    success=False,
                    output=out,
                    error=f"Exit {rc}\n{err}",
                    metadata={"return_code": rc},
                )
            return ToolResult(
                success=True,
                output=out + ("\n[output truncated]" if truncated else ""),
                metadata={"return_code": rc},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Subprocess error: {e}")


class GetWeatherTool(CLITool):
    """Get current weather for a location via Open-Meteo."""

    def __init__(self) -> None:
        super().__init__(
            name="get_weather",
            description=(
                "Get current weather for a location. Use unit=celsius unless the user "
                "asks for Fahrenheit. If lookup fails, retry once with a more explicit "
                "location string (e.g. 'Hamilton, Ontario, Canada') before asking the user."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name.",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Temperature unit (default: celsius)",
                    },
                },
                "required": ["location"],
            },
            command=[sys.executable, "-m", "proxi.scripts.weather", "current"],
            timeout=30,
            parallel_safe=True,
            defer_loading=True,
        )


class GetWeatherForecastTool(CLITool):
    """Get a multi-day weather forecast for a location via Open-Meteo."""

    def __init__(self) -> None:
        super().__init__(
            name="get_weather_forecast",
            description=(
                "Get a multi-day weather forecast for a location. Use when the user asks "
                "about upcoming days or a date range. Days are capped at 7."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name.",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of forecast days (1-7, default: 3)",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Temperature unit (default: celsius)",
                    },
                },
                "required": ["location"],
            },
            command=[sys.executable, "-m", "proxi.scripts.weather", "forecast"],
            timeout=30,
            parallel_safe=True,
            defer_loading=True,
        )


# Registry of all CLI tools.  auto_load_cli_tools() iterates this list and
# applies the defer_loading / always_load config from config/mcp.json.
# To add a new CLI tool: subclass CLITool above, then append it here.
CLI_TOOLS: list[type[CLITool]] = [
    GetWeatherTool,
    GetWeatherForecastTool,
]
