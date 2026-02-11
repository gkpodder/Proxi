"""Datetime tool for providing current date and time."""

from datetime import datetime, timezone

from proxi.tools.base import BaseTool, ToolResult


class DateTimeTool(BaseTool):
    """Tool that returns the current date and time for the agent to use."""

    def __init__(self):
        """Initialize the datetime tool."""
        super().__init__(
            name="get_datetime",
            description="Get the current date and time. Use this when you need to know today's date, the current time, or temporal context (e.g. for scheduling, relative dates, or time-sensitive tasks).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Optional IANA timezone name (e.g. 'America/New_York'). If omitted, returns UTC.",
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

                    tz = ZoneInfo(tz_name)
                    now = datetime.now(tz)
                except Exception as e:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Invalid timezone '{tz_name}': {e}",
                    )
            else:
                now = datetime.now(timezone.utc)

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
