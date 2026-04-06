"""CLI wrapper for Gmail MCP tool operations.

Exit code contract:
  0 - Script ran to completion. stdout is a JSON object.
      The JSON may contain an "error" key if the API reported a problem.
  1 - Unrecoverable script failure (bad args, import error, unexpected exception).
      stdout is a JSON object with "error" and "hint".
  3 - Transient network failure. stdout is a JSON object with "error" and "hint".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import urllib.error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Gmail operations via CLI",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    read = sub.add_parser("read", help="Read emails", allow_abbrev=False)
    read.add_argument("--max-results", type=int, default=10, help="Max emails")
    read.add_argument("--query", default="", help="Gmail search query")

    send = sub.add_parser("send", help="Send email", allow_abbrev=False)
    send.add_argument("--to", required=True, help="Recipient email")
    send.add_argument("--subject", default="(no subject)", help="Email subject")
    send.add_argument("--body", required=True, help="Email body")
    send.add_argument("--cc", default=None, help="Optional CC")
    send.add_argument("--bcc", default=None, help="Optional BCC")

    get = sub.add_parser("get", help="Get email details", allow_abbrev=False)
    get.add_argument("--email-id", required=True, help="Gmail message ID")

    args = parser.parse_args()

    try:
        from proxi.mcp.servers.gmail_tools import GmailTools

        tools = GmailTools()

        if args.cmd == "read":
            result = asyncio.run(tools.read_emails(args.max_results, args.query))
        elif args.cmd == "send":
            result = asyncio.run(
                tools.send_email(args.to, args.subject, args.body, args.cc, args.bcc)
            )
        else:
            result = asyncio.run(tools.get_email(args.email_id))

        print(json.dumps(result))
        sys.exit(0)

    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        print(
            json.dumps(
                {
                    "error": str(e),
                    "hint": "Transient network error. Retrying may succeed.",
                }
            )
        )
        sys.exit(3)
    except Exception as e:
        print(
            json.dumps(
                {
                    "error": str(e),
                    "hint": (
                        "This is a script-level failure, not an API error. "
                        "Check Gmail credentials/config or try again."
                    ),
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
