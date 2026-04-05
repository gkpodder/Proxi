"""CLI-backed tools: fixed commands, structured args → CLI flags.

Pattern for adding a new CLI tool:
  1. Write a script under proxi/scripts/ with argparse subcommands or flags.
     - Exit 0 when the script ran to completion (even if the API returned an error).
       Put the API error in the JSON output — the agent reads it and can retry.
     - Exit non-zero only for unrecoverable script failures (bad args, import errors,
       total network failure). Always print a structured JSON error to stdout, not a
       raw traceback.
  2. Subclass CLITool, set command=[sys.executable, "-m", "proxi.scripts.<name>", ...].
  3. Set integration_name to the integration key from proxi/integrations/catalog.py,
     or None for core tools that are always available (e.g. web_search).
  4. Append the new class to CLI_TOOLS at the bottom of this file.
  5. Adjust config/integrations.json always_load if it should be live instead of deferred.
  6. Mark parallel_safe=True only if the script has no shared mutable state between
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

    Set ``integration_name`` on the subclass to the integration key from
    proxi/integrations/catalog.py (e.g. "gmail", "spotify").  Tools with
    ``integration_name = None`` are always available (e.g. web_search).
    """

    # Subclasses set this to the integration they belong to, or None for core tools.
    integration_name: str | None = None

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
        if self.integration_name is not None:
            from proxi.security.key_store import is_integration_enabled
            if not is_integration_enabled(self.integration_name):
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Integration '{self.integration_name}' is not enabled. "
                        "Enable it in Settings → Integrations."
                    ),
                )

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

    integration_name = "weather"

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

    integration_name = "weather"

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


class NotionListChildrenTool(CLITool):
    """List child pages/databases under the configured Notion parent page."""

    integration_name = "notion"

    def __init__(self) -> None:
        super().__init__(
            name="notion_list_children",
            description=(
                "List child pages/databases under the configured parent page. "
                "Use this for requests like 'show my Notion pages'. If the result "
                "contains an error field, report it and ask follow-up only if needed."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of items to retrieve (default: 10)",
                    }
                },
                "required": [],
            },
            command=[sys.executable, "-m", "proxi.scripts.notion", "list-children"],
            timeout=30,
            # parallel_safe: stateless HTTP calls, no shared mutable state.
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


class NotionCreatePageTool(CLITool):
    """Create a Notion page under the configured parent page."""

    integration_name = "notion"

    def __init__(self) -> None:
        super().__init__(
            name="notion_create_page",
            description=(
                "Create a new Notion page under the configured parent page. Always "
                "pass title. Content is optional. If output contains an error field, "
                "surface it and ask a follow-up only if needed."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Page title",
                    },
                    "content": {
                        "type": "string",
                        "description": "Optional page content",
                    },
                },
                "required": ["title"],
            },
            command=[sys.executable, "-m", "proxi.scripts.notion", "create-page"],
            timeout=30,
            parallel_safe=True,
            read_only=False,
            defer_loading=True,
            max_retries=2,
        )


class NotionAppendToPageTool(CLITool):
    """Append paragraph content to an existing Notion page."""

    integration_name = "notion"

    def __init__(self) -> None:
        super().__init__(
            name="notion_append_to_page",
            description=(
                "Append content to an existing Notion page. Always pass page_id and "
                "content. If output contains an error field, surface it and ask for "
                "clarification only when required."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "Notion page ID",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to append",
                    },
                },
                "required": ["page_id", "content"],
            },
            command=[sys.executable, "-m", "proxi.scripts.notion", "append-to-page"],
            timeout=30,
            parallel_safe=True,
            read_only=False,
            defer_loading=True,
            max_retries=2,
        )


class NotionGetPageTool(CLITool):
    """Get details for a Notion page by page ID."""

    integration_name = "notion"

    def __init__(self) -> None:
        super().__init__(
            name="notion_get_page",
            description=(
                "Get details for a Notion page. Always pass page_id. If output "
                "contains an error field, surface it and ask follow-up only if needed."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "Notion page ID",
                    },
                },
                "required": ["page_id"],
            },
            command=[sys.executable, "-m", "proxi.scripts.notion", "get-page"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


class ReadEmailsTool(CLITool):
    """Read Gmail inbox messages via CLI wrapper."""

    integration_name = "gmail"

    def __init__(self) -> None:
        super().__init__(
            name="read_emails",
            description=(
                "Read emails from Gmail. Use max_results (default 10) and optional "
                "query. If the result contains an error field, report it and ask "
                "follow-up only if needed."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of emails to retrieve (default: 10)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional Gmail search query",
                    },
                },
                "required": [],
            },
            command=[sys.executable, "-m", "proxi.scripts.gmail", "read"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


class SendEmailTool(CLITool):
    """Send Gmail message via CLI wrapper."""

    integration_name = "gmail"

    def __init__(self) -> None:
        super().__init__(
            name="send_email",
            description=(
                "Send an email via Gmail. Require to and body. Subject defaults to "
                "(no subject). Optional cc and bcc are supported."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"},
                    "cc": {"type": "string", "description": "CC email addresses"},
                    "bcc": {"type": "string", "description": "BCC email addresses"},
                },
                "required": ["to", "body"],
            },
            command=[sys.executable, "-m", "proxi.scripts.gmail", "send"],
            timeout=30,
            parallel_safe=True,
            read_only=False,
            defer_loading=True,
            max_retries=2,
        )


class GetEmailTool(CLITool):
    """Get a specific Gmail message by ID via CLI wrapper."""

    integration_name = "gmail"

    def __init__(self) -> None:
        super().__init__(
            name="get_email",
            description=(
                "Get details for a specific Gmail message by email_id."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": "Gmail message ID",
                    },
                },
                "required": ["email_id"],
            },
            command=[sys.executable, "-m", "proxi.scripts.gmail", "get"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


class CalendarListEventsTool(CLITool):
    """List calendar events via CLI wrapper."""

    integration_name = "google_calendar"

    def __init__(self) -> None:
        super().__init__(
            name="calendar_list_events",
            description=(
                "List upcoming Google Calendar events. Supports max_results, "
                "calendar_id, optional time_min/time_max, and optional query."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Maximum number of events"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "time_min": {"type": "string", "description": "RFC3339 lower bound"},
                    "time_max": {"type": "string", "description": "RFC3339 upper bound"},
                    "query": {"type": "string", "description": "Optional free-text search query"},
                },
                "required": [],
            },
            command=[sys.executable, "-m", "proxi.scripts.calendar", "list-events"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


class CalendarCreateEventTool(CLITool):
    """Create a calendar event via CLI wrapper."""

    integration_name = "google_calendar"

    def __init__(self) -> None:
        super().__init__(
            name="calendar_create_event",
            description=(
                "Create a Google Calendar event. Requires summary, start_time, "
                "end_time, timezone, and attendees."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title"},
                    "start_time": {"type": "string", "description": "Event start date-time"},
                    "end_time": {"type": "string", "description": "Event end date-time"},
                    "timezone": {"type": "string", "description": "IANA timezone name"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of attendee emails",
                    },
                    "description": {"type": "string", "description": "Event description"},
                    "location": {"type": "string", "description": "Event location"},
                },
                "required": ["summary", "start_time", "end_time", "timezone", "attendees"],
            },
            command=[sys.executable, "-m", "proxi.scripts.calendar", "create-event"],
            timeout=30,
            parallel_safe=True,
            read_only=False,
            defer_loading=True,
            max_retries=2,
        )


class CalendarGetEventTool(CLITool):
    """Get a calendar event by ID via CLI wrapper."""

    integration_name = "google_calendar"

    def __init__(self) -> None:
        super().__init__(
            name="calendar_get_event",
            description="Get details of a specific Google Calendar event by event_id.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Google Calendar event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                },
                "required": ["event_id"],
            },
            command=[sys.executable, "-m", "proxi.scripts.calendar", "get-event"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=2,
        )


class CalendarUpdateEventTool(CLITool):
    """Update a calendar event via CLI wrapper."""

    integration_name = "google_calendar"

    def __init__(self) -> None:
        super().__init__(
            name="calendar_update_event",
            description=(
                "Update fields of an existing Google Calendar event. Requires event_id "
                "plus one or more fields to change."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Google Calendar event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "summary": {"type": "string", "description": "Updated event title"},
                    "start_time": {"type": "string", "description": "Updated start date-time"},
                    "end_time": {"type": "string", "description": "Updated end date-time"},
                    "timezone": {"type": "string", "description": "Updated IANA timezone"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated attendee email list",
                    },
                    "description": {"type": "string", "description": "Updated event description"},
                    "location": {"type": "string", "description": "Updated event location"},
                },
                "required": ["event_id"],
            },
            command=[sys.executable, "-m", "proxi.scripts.calendar", "update-event"],
            timeout=30,
            parallel_safe=True,
            read_only=False,
            defer_loading=True,
            max_retries=2,
        )


class CalendarDeleteEventTool(CLITool):
    """Delete a calendar event via CLI wrapper."""

    integration_name = "google_calendar"

    def __init__(self) -> None:
        super().__init__(
            name="calendar_delete_event",
            description="Delete a Google Calendar event by event_id.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Google Calendar event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                },
                "required": ["event_id"],
            },
            command=[sys.executable, "-m", "proxi.scripts.calendar", "delete-event"],
            timeout=30,
            parallel_safe=True,
            read_only=False,
            defer_loading=True,
            max_retries=2,
        )


class ObsidianListVaultsTool(CLITool):
    """List discovered Obsidian vaults via CLI wrapper."""

    integration_name = "obsidian"

    def __init__(self) -> None:
        super().__init__(
            name="obsidian_list_vaults",
            description="List discovered Obsidian vaults.",
            parameters_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            command=[sys.executable, "-m", "proxi.scripts.obsidian", "list-vaults"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=0,
        )


class ObsidianListNotesTool(CLITool):
    """List notes in selected Obsidian vault via CLI wrapper."""

    integration_name = "obsidian"

    def __init__(self) -> None:
        super().__init__(
            name="obsidian_list_notes",
            description="List markdown notes in an Obsidian vault.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "vault_name": {"type": "string", "description": "Vault name"},
                    "vault_path": {"type": "string", "description": "Absolute vault path"},
                    "max_results": {"type": "integer", "description": "Maximum number of notes"},
                },
                "required": [],
            },
            command=[sys.executable, "-m", "proxi.scripts.obsidian", "list-notes"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=0,
        )


class ObsidianReadNoteTool(CLITool):
    """Read an Obsidian note via CLI wrapper."""

    integration_name = "obsidian"

    def __init__(self) -> None:
        super().__init__(
            name="obsidian_read_note",
            description="Read an Obsidian note by note_path.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "vault_name": {"type": "string", "description": "Vault name"},
                    "vault_path": {"type": "string", "description": "Absolute vault path"},
                    "note_path": {"type": "string", "description": "Path to note within vault"},
                },
                "required": ["note_path"],
            },
            command=[sys.executable, "-m", "proxi.scripts.obsidian", "read-note"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=0,
        )


class ObsidianCreateNoteTool(CLITool):
    """Create an Obsidian note via CLI wrapper."""

    integration_name = "obsidian"

    def __init__(self) -> None:
        super().__init__(
            name="obsidian_create_note",
            description="Create a note in an Obsidian vault.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "vault_name": {"type": "string", "description": "Vault name"},
                    "vault_path": {"type": "string", "description": "Absolute vault path"},
                    "note_path": {"type": "string", "description": "Path to note within vault"},
                    "content": {"type": "string", "description": "Markdown content"},
                    "overwrite": {"type": "boolean", "description": "Overwrite existing note"},
                },
                "required": ["note_path", "content"],
            },
            command=[sys.executable, "-m", "proxi.scripts.obsidian", "create-note"],
            timeout=30,
            parallel_safe=False,
            read_only=False,
            defer_loading=True,
            max_retries=0,
        )


class ObsidianUpdateNoteTool(CLITool):
    """Update an Obsidian note via CLI wrapper."""

    integration_name = "obsidian"

    def __init__(self) -> None:
        super().__init__(
            name="obsidian_update_note",
            description="Update content of an existing Obsidian note.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "vault_name": {"type": "string", "description": "Vault name"},
                    "vault_path": {"type": "string", "description": "Absolute vault path"},
                    "note_path": {"type": "string", "description": "Path to note within vault"},
                    "content": {"type": "string", "description": "Markdown content"},
                    "append": {"type": "boolean", "description": "Append instead of replace"},
                },
                "required": ["note_path", "content"],
            },
            command=[sys.executable, "-m", "proxi.scripts.obsidian", "update-note"],
            timeout=30,
            parallel_safe=False,
            read_only=False,
            defer_loading=True,
            max_retries=0,
        )


class ObsidianSearchNotesTool(CLITool):
    """Search notes in Obsidian vault via CLI wrapper."""

    integration_name = "obsidian"

    def __init__(self) -> None:
        super().__init__(
            name="obsidian_search_notes",
            description="Search Obsidian notes by query.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "vault_name": {"type": "string", "description": "Vault name"},
                    "vault_path": {"type": "string", "description": "Absolute vault path"},
                    "query": {"type": "string", "description": "Search text"},
                    "max_results": {"type": "integer", "description": "Maximum number of matches"},
                },
                "required": ["query"],
            },
            command=[sys.executable, "-m", "proxi.scripts.obsidian", "search-notes"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=0,
        )


class ObsidianGetNoteMetadataTool(CLITool):
    """Get Obsidian note metadata via CLI wrapper."""

    integration_name = "obsidian"

    def __init__(self) -> None:
        super().__init__(
            name="obsidian_get_note_metadata",
            description="Get metadata/frontmatter for an Obsidian note.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "vault_name": {"type": "string", "description": "Vault name"},
                    "vault_path": {"type": "string", "description": "Absolute vault path"},
                    "note_path": {"type": "string", "description": "Path to note within vault"},
                },
                "required": ["note_path"],
            },
            command=[sys.executable, "-m", "proxi.scripts.obsidian", "get-note-metadata"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=0,
        )


class WebSearchTool(CLITool):
    """Search the web using DuckDuckGo from natural language queries."""

    def __init__(self) -> None:
        super().__init__(
            name="web_search",
            description=(
                "Search the web for information on any topic. Returns up to 5 relevant "
                "results with titles, URLs, and descriptions. Use natural language queries "
                "like 'weather today' or 'Python async patterns'. If results seem limited, "
                "try a more specific query. For current-events and news requests, do not "
                "ask the user for a time window, source preference, or format preference "
                "unless they explicitly request customization; use a sensible default and "
                "search immediately."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query (e.g., 'climate change impacts')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5, max: 20)",
                    },
                },
                "required": ["query"],
            },
            command=[sys.executable, "-m", "proxi.scripts.web_search"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=1,
        )


class WebExtractTool(CLITool):
    """Extract and convert web page content to markdown from URLs."""

    def __init__(self) -> None:
        super().__init__(
            name="web_extract",
            description=(
                "Extract content from web page URLs and convert to markdown. Returns page "
                "content in markdown format. Also works with PDF URLs — pass the PDF link "
                "directly. Pages under 10,000 characters return full content; larger pages "
                "are truncated with a note. Useful for reading articles, documentation, "
                "and web content without leaving the conversation."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to fetch (e.g., 'https://example.com/article')",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return before summarizing/truncating (default: 10000)",
                    },
                },
                "required": ["url"],
            },
            command=[sys.executable, "-m", "proxi.scripts.web_extract"],
            timeout=30,
            parallel_safe=True,
            read_only=True,
            defer_loading=True,
            max_retries=1,
        )


# Registry of all CLI tools.  auto_load_cli_tools() iterates this list and
# applies the defer_loading / always_load config from config/integrations.json.
# To add a new CLI tool: subclass CLITool above, set integration_name, then append it here.
CLI_TOOLS: list[type[CLITool]] = [
    GetWeatherTool,
    GetWeatherForecastTool,
    NotionListChildrenTool,
    NotionCreatePageTool,
    NotionAppendToPageTool,
    NotionGetPageTool,
    ReadEmailsTool,
    SendEmailTool,
    GetEmailTool,
    CalendarListEventsTool,
    CalendarCreateEventTool,
    CalendarGetEventTool,
    CalendarUpdateEventTool,
    CalendarDeleteEventTool,
    ObsidianListVaultsTool,
    ObsidianListNotesTool,
    ObsidianReadNoteTool,
    ObsidianCreateNoteTool,
    ObsidianUpdateNoteTool,
    ObsidianSearchNotesTool,
    ObsidianGetNoteMetadataTool,
    WebSearchTool,
    WebExtractTool,
]
