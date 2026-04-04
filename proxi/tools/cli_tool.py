"""CLI-backed tools: fixed commands, structured args → CLI flags.

Pattern for adding a new CLI tool:
  1. Write a script under proxi/scripts/ with argparse subcommands or flags.
     - Exit 0 when the script ran to completion (even if the API returned an error).
       Put the API error in the JSON output — the agent reads it and can retry.
     - Exit non-zero only for unrecoverable script failures (bad args, import errors,
       total network failure). Always print a structured JSON error to stdout, not a
       raw traceback.
  2. Subclass CLITool, set command=[sys.executable, "-m", "proxi.scripts.<name>", ...].
  3. Append the new class to CLI_TOOLS at the bottom of this file.
  4. Adjust config/mcp.json cliTools.always_load if it should be live instead of deferred.
  5. Mark parallel_safe=True only if the script has no shared mutable state between
     concurrent invocations (stateless HTTP calls are fine; file writes are not).
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
from pathlib import Path
from typing import Any

from proxi.tools.base import BaseTool, ToolResult

_MAX_OUTPUT = 15_000
# Time to wait for graceful SIGTERM shutdown before escalating to SIGKILL.
_SIGTERM_GRACE_SECONDS = 5.0


class CLITool(BaseTool):
    """Base class for tools backed by a pre-configured CLI script.

    Subclasses define ``command`` in ``__init__``; the LLM never composes it.
    Structured arguments from the LLM are translated to ``--flag=value`` CLI
    pairs by ``_build_argv``.  The ``=`` form is used deliberately to prevent
    flag injection: argparse always treats everything after ``=`` as a literal
    value, even if it starts with ``--``.

    Subclasses can override ``_build_argv`` for non-standard argument layouts.

    Timeout handling uses a two-stage escalation:
      1. SIGTERM — gives the process a chance to flush output and clean up.
      2. After _SIGTERM_GRACE_SECONDS, SIGKILL — unconditional termination.
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
        read_only: bool = False,
        defer_loading: bool = True,
        working_dir: Path | None = None,
        max_retries: int = 0,
        retry_base_delay: float = 1.0,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            parallel_safe=parallel_safe,
            read_only=read_only,
            parameters_schema=parameters_schema,
        )
        self._command = command
        self._timeout = timeout
        self.defer_loading = defer_loading
        self._working_dir = working_dir
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

    def _build_argv(self, arguments: dict[str, Any]) -> list[str]:
        """Translate ``{key: value}`` arguments to ``--key=value`` CLI flags.

        Rules:
        - ``None`` or ``False``  → skip (flag omitted)
        - ``True``               → ``--flag`` (bare flag, no value)
        - ``list``               → ``--flag=val1 --flag=val2`` (repeated)
        - everything else        → ``--flag=str(value)``
        - underscores in keys    → hyphens (``temperature_unit`` → ``--temperature-unit``)

        The ``--flag=value`` (equals) form prevents flag injection: if the LLM
        passes ``{"location": "--unit=fahrenheit"}``, argparse receives
        ``--location=--unit=fahrenheit`` and treats the entire right-hand side
        as the value of ``--location``, not as a separate flag.
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
                    argv.append(f"{flag}={item}")
            else:
                argv.append(f"{flag}={value}")
        return argv

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        argv = self._command + self._build_argv(arguments)
        start = time.monotonic()
        last_result: ToolResult | None = None

        for attempt in range(self._max_retries + 1):
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._working_dir,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=float(self._timeout)
                    )
                except asyncio.TimeoutError:
                    # Stage 1: graceful shutdown via SIGTERM
                    process.terminate()
                    try:
                        await asyncio.wait_for(
                            process.wait(), timeout=_SIGTERM_GRACE_SECONDS
                        )
                    except asyncio.TimeoutError:
                        # Stage 2: forceful kill
                        process.kill()
                        await process.wait()
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Tool timed out after {self._timeout}s",
                        metadata={"elapsed_ms": elapsed_ms},
                    )

                elapsed_ms = int((time.monotonic() - start) * 1000)
                out = stdout.decode("utf-8", errors="replace")
                err = stderr.decode("utf-8", errors="replace").strip()
                rc = process.returncode

                # Truncate and always annotate — applies to both success and failure paths.
                truncated = len(out) > _MAX_OUTPUT
                if truncated:
                    out = out[:_MAX_OUTPUT] + "\n[output truncated at 15,000 chars]"

                if rc != 0:
                    # Exit code 3 signals a transient failure — retry with backoff.
                    if rc == 3 and attempt < self._max_retries:
                        delay = self._retry_base_delay * (2 ** attempt) * (0.9 + 0.2 * random.random())
                        await asyncio.sleep(delay)
                        continue

                    # Include stdout in the error so the agent sees any structured
                    # error payload the script wrote before exiting non-zero.
                    error_parts = [f"Exit {rc}"]
                    if out:
                        error_parts.append(f"Output:\n{out}")
                    if err:
                        error_parts.append(f"Stderr:\n{err}")
                    last_result = ToolResult(
                        success=False,
                        output=out,
                        error="\n".join(error_parts),
                        metadata={"return_code": rc, "elapsed_ms": elapsed_ms},
                    )
                    break

                # Append stderr warnings to successful output so the agent sees them.
                if err:
                    out += f"\n[stderr]\n{err}"

                last_result = ToolResult(
                    success=True,
                    output=out,
                    metadata={"return_code": rc, "elapsed_ms": elapsed_ms},
                )
                break

            except Exception as e:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                last_result = ToolResult(
                    success=False,
                    output="",
                    error=f"Subprocess error: {e}",
                    metadata={"elapsed_ms": elapsed_ms},
                )
                break

        return last_result  # type: ignore[return-value]


class GetWeatherTool(CLITool):
    """Get current weather for a location via Open-Meteo."""

    def __init__(self) -> None:
        super().__init__(
            name="get_weather",
            description=(
                "Get current weather for a location. Always pass `location` in args "
                "(via call_tool); omitting it yields a CLI usage error, not an API "
                "response. Use unit=celsius unless the user asks for Fahrenheit. Do not "
                "use this tool when the user asks for a forecast or upcoming weather—use "
                "call_tool to discover and invoke get_weather_forecast instead. If the "
                "result contains an error field, retry once with a more explicit "
                "location string (e.g. 'Hamilton, Ontario, Canada') before asking the "
                "user."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "City or place name. Required in args — the script fails "
                            "with 'required: --location' if omitted."
                        ),
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
            # parallel_safe: each invocation is a stateless HTTP call to Open-Meteo
            # with no shared mutable state, so concurrent calls are safe.
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


class GetWeatherForecastTool(CLITool):
    """Get a multi-day weather forecast for a location via Open-Meteo."""

    def __init__(self) -> None:
        super().__init__(
            name="get_weather_forecast",
            description=(
                "Get a multi-day weather forecast for a location. Always pass `location` "
                "in args (via call_tool); omitting it yields a CLI usage error "
                "('--location' required), not an API response. Use when the user asks "
                "about upcoming days or a date range. Days are capped at 7. If the result "
                "contains an error field, retry with a more explicit location string."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "City or place name. Required in args — the script fails "
                            "with 'required: --location' if omitted."
                        ),
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
            # parallel_safe: stateless HTTP calls, no shared mutable state.
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


# Registry of all CLI tools.  auto_load_cli_tools() iterates this list and
# applies the defer_loading / always_load config from config/mcp.json.
# To add a new CLI tool: subclass CLITool above, then append it here.
CLI_TOOLS: list[type[CLITool]] = [
    GetWeatherTool,
    GetWeatherForecastTool,
]
