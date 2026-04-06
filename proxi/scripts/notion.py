"""CLI wrapper for Notion MCP tool operations.

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
import sys
import urllib.error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Notion operations via CLI",
        # Disable abbreviation matching to prevent partial-flag confusion.
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_children = sub.add_parser(
        "list-children",
        help="List child pages/databases under configured parent page",
        allow_abbrev=False,
    )
    list_children.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum number of items to return",
    )

    create_page = sub.add_parser(
        "create-page",
        help="Create a page under the configured parent page",
        allow_abbrev=False,
    )
    create_page.add_argument("--title", required=True, help="Page title")
    create_page.add_argument(
        "--content",
        default=None,
        help="Optional paragraph content for the new page",
    )

    append_page = sub.add_parser(
        "append-to-page",
        help="Append paragraph content to a Notion page",
        allow_abbrev=False,
    )
    append_page.add_argument("--page-id", required=True, help="Notion page ID")
    append_page.add_argument("--content", required=True, help="Content to append")

    get_page = sub.add_parser(
        "get-page",
        help="Get metadata/details for a Notion page",
        allow_abbrev=False,
    )
    get_page.add_argument("--page-id", required=True, help="Notion page ID")

    args = parser.parse_args()

    try:
        from proxi.mcp.servers.notion_tools import NotionTools

        notion = NotionTools()

        if args.cmd == "list-children":
            result = asyncio.run(notion.list_children(args.max_results))
        elif args.cmd == "create-page":
            result = asyncio.run(notion.create_page(args.title, args.content))
        elif args.cmd == "append-to-page":
            result = asyncio.run(notion.append_to_page(args.page_id, args.content))
        else:
            result = asyncio.run(notion.get_page(args.page_id))

        print(json.dumps(result))
        sys.exit(0)

    except (urllib.error.URLError, TimeoutError) as e:
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
                        "Check Notion credentials/config or try again."
                    ),
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
