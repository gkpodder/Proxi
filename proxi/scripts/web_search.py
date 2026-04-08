"""CLI wrapper for DuckDuckGo web search.

Exit code contract:
  0 — Script ran to completion. stdout is a JSON object with "results" array.
      Each result has: title, url, description, source_domain, rank.
      If no results found, results array is empty (not an error).
  1 — Unrecoverable script failure (import error, bad arguments,
      unexpected exception). stdout is a JSON object with "error" and "hint" keys.
  3 — Transient failure (network/provider timeout/rate limiting). stdout is JSON
      with "error", "hint", and "transient": true.
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse

_DEFAULT_MAX_RESULTS = 5
_MAX_RESULTS_LIMIT = 20
_VALID_SAFESEARCH = {"off", "moderate", "strict"}
_VALID_TIME_LIMIT = {"d", "w", "m", "y"}


def _clamp_max_results(value: int) -> int:
    return max(1, min(value, _MAX_RESULTS_LIMIT))


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_transient_error(exc: Exception) -> bool:
    """Heuristic for failures that can succeed on retry."""
    message = str(exc).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "temporarily unavailable",
        "rate limit",
        "too many requests",
        "connection reset",
        "connection aborted",
        "connection error",
        "name or service not known",
        "temporary failure in name resolution",
        "service unavailable",
    )
    if any(marker in message for marker in transient_markers):
        return True

    transient_exception_names = {
        "timeout",
        "readtimeout",
        "connecttimeout",
        "connectionerror",
        "httpstatuserror",
    }
    for cls in type(exc).mro():
        if cls.__name__.lower() in transient_exception_names:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search the web using DuckDuckGo",
        allow_abbrev=False,
    )
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument(
        "--max-results",
        type=int,
        default=_DEFAULT_MAX_RESULTS,
        help="Maximum number of results (default: 5, max: 20)",
    )
    parser.add_argument(
        "--site",
        help="Restrict results to a specific domain (e.g., example.com)",
    )
    parser.add_argument(
        "--region",
        help="Search region hint for DuckDuckGo (e.g., us-en)",
    )
    parser.add_argument(
        "--safesearch",
        choices=sorted(_VALID_SAFESEARCH),
        default="moderate",
        help="Safe search level (off|moderate|strict, default: moderate)",
    )
    parser.add_argument(
        "--time-limit",
        choices=sorted(_VALID_TIME_LIMIT),
        help="Recency filter: d=day, w=week, m=month, y=year",
    )

    args = parser.parse_args()
    max_results = _clamp_max_results(args.max_results)
    query = args.query.strip()
    if args.site:
        query = f"{query} site:{args.site.strip()}"

    try:
        from ddgs import DDGS

        results = []
        with DDGS() as ddgs:
            for rank, result in enumerate(
                ddgs.text(
                    query,
                    max_results=max_results,
                    region=args.region,
                    safesearch=args.safesearch,
                    timelimit=args.time_limit,
                ),
                start=1,
            ):
                url = result.get("href", "")
                results.append({
                    "title": result.get("title", ""),
                    "url": url,
                    "description": result.get("body", ""),
                    "source_domain": _extract_domain(url),
                    "rank": rank,
                })

        print(json.dumps({
            "query": query,
            "original_query": args.query,
            "site": args.site,
            "region": args.region,
            "safesearch": args.safesearch,
            "time_limit": args.time_limit,
            "max_results": max_results,
            "results": results,
            "count": len(results),
        }))
        sys.exit(0)

    except ImportError as e:
        print(json.dumps({
            "error": str(e),
            "hint": (
                "Missing dependency: install via 'pip install ddgs' "
                "or 'uv pip install ddgs'"
            ),
        }))
        sys.exit(1)
    except Exception as e:
        if _is_transient_error(e):
            print(json.dumps({
                "error": str(e),
                "hint": "Transient search/provider failure. Safe to retry.",
                "transient": True,
            }))
            sys.exit(3)
        print(json.dumps({
            "error": str(e),
            "hint": (
                "This is a script-level failure. Check query format or try again."
            ),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
