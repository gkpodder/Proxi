"""CLI wrapper for DuckDuckGo web search.

Exit code contract:
  0 — Script ran to completion. stdout is a JSON object with "results" array.
      Each result has: title, url, description.
      If no results found, results array is empty (not an error).
  1 — Unrecoverable script failure (import error, bad arguments,
      unexpected exception). stdout is a JSON object with "error" and "hint" keys.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search the web using DuckDuckGo",
        allow_abbrev=False,
    )
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum number of results (default: 5)",
    )

    args = parser.parse_args()

    try:
        from ddgs import DDGS

        # Use context manager for proper cleanup
        results = []
        with DDGS() as ddgs:
            # DDGS.text() returns generator, so collect into list
            for result in ddgs.text(args.query, max_results=args.max_results):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "description": result.get("body", ""),
                })

        # Always exit 0 when we got results from the search engine
        print(json.dumps({
            "query": args.query,
            "results": results,
            "count": len(results),
        }))
        sys.exit(0)

    except ImportError as e:
        # Missing ddgs package
        print(json.dumps({
            "error": str(e),
            "hint": (
                "Missing dependency: install via 'pip install ddgs' "
                "or 'uv pip install ddgs'"
            ),
        }))
        sys.exit(1)
    except Exception as e:
        # Unrecoverable failure: bad args, logic error, etc.
        print(json.dumps({
            "error": str(e),
            "hint": (
                "This is a script-level failure. Check query format or try again."
            ),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
