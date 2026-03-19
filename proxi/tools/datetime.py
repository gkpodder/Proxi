"""Datetime tool for providing current date and time."""

from datetime import datetime, timezone as dt_timezone

from proxi.tools.base import BaseTool, ToolResult


class DateTimeTool(BaseTool):
    """Tool that returns the current date and time for the agent to use."""

    def __init__(self):
        """Initialize the datetime tool."""
        super().__init__(
            name="get_datetime",
            description="Get the current date and time. Use this when you need to know today's date, the current time, or temporal context (e.g. for scheduling, relative dates, or time-sensitive tasks). Supports IANA timezone names (e.g. 'America/Toronto') and common aliases (e.g. 'EST', 'PST').",
            parallel_safe=True,
            parameters_schema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Optional IANA timezone name (e.g. 'America/New_York', 'America/Toronto') or alias (e.g. 'EST', 'PST'). If omitted, returns UTC.",
                    },
                },
                "required": [],
            },
        )

    async def execute(self, arguments: dict[str, str]) -> ToolResult:
        """Return the current date and time."""
        tz_name = arguments.get("timezone") if arguments else None

        try:
            if tz_name:
                try:
                    from zoneinfo import ZoneInfo

                    # Try to normalize the timezone (handles aliases like EST, PST, etc.)
                    from proxi.mcp.servers.calendar_tools import CalendarTools

                    normalized_tz = CalendarTools._normalize_timezone(tz_name)
                    if not normalized_tz:
                        return ToolResult(
                            success=False,
                            output="",
                            error=f"Timezone '{tz_name}' not recognized. Use IANA format (e.g. America/Toronto) or an alias (EST, PST, etc.).",
                        )

                    tz = ZoneInfo(normalized_tz)
                    now = datetime.now(tz)
                except ImportError:
                    # Fallback if ZoneInfo not available
                    return ToolResult(
                        success=False,
                        output="",
                        error="Timezone support not available. Please try again.",
                    )
                except Exception as e:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Error with timezone '{tz_name}': {str(e)}",
                    )
            else:
                now = datetime.now(dt_timezone.utc)

            # Human-readable and ISO format for the agent
            iso = now.isoformat()
            friendly = now.strftime("%A, %B %d, %Y at %I:%M %p %Z")

            output = f"Current date and time:\n- ISO 8601: {iso}\n- Friendly: {friendly}"
            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "iso": iso,
                    "year": now.year,
                    "month": now.month,
                    "day": now.day,
                    "hour": now.hour,
                    "minute": now.minute,
                    "second": now.second,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error getting datetime: {str(e)}",
            )
