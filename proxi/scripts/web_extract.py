"""CLI wrapper for extracting web page content.

Exit code contract:
  0 — Script ran to completion. stdout is a JSON object with content/summary.
      If content extraction failed but we got a response, returns empty content
      with a note (not an error).
  1 — Unrecoverable script failure (bad URL, import error, no network).
      stdout is a JSON object with "error" and "hint" keys.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract content from a web page",
        allow_abbrev=False,
    )
    parser.add_argument("--url", required=True, help="Web page URL")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=10000,
        help="Maximum characters to return before summarizing (default: 10000)",
    )

    args = parser.parse_args()

    try:
        import requests
        from readability import Document
        import html2text

        # Fetch the page with a reasonable timeout
        try:
            response = requests.get(args.url, timeout=15, allow_redirects=True)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            print(json.dumps({
                "error": "Request timeout",
                "hint": "The webpage took too long to load. Try a different URL.",
            }))
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(json.dumps({
                "error": str(e),
                "hint": "Failed to fetch URL. Check if the URL is valid and accessible.",
            }))
            sys.exit(1)

        # Extract main content using readability
        doc = Document(response.text)
        content_html = doc.summary()

        # Convert HTML to markdown
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        markdown_content = h.handle(content_html)

        # Normalize whitespace
        markdown_content = markdown_content.strip()

        # Check if we need to summarize
        is_summarized = False
        if len(markdown_content) > args.max_chars:
            is_summarized = True
            # Simple truncation with ellipsis
            markdown_content = markdown_content[:args.max_chars] + "\n\n[Content truncated — full article exceeds " + str(args.max_chars) + " characters]"

        # Always exit 0 when we got a response from the webpage
        print(json.dumps({
            "url": args.url,
            "title": doc.title() or "Untitled",
            "content": markdown_content,
            "char_count": len(markdown_content),
            "is_summarized": is_summarized,
        }))
        sys.exit(0)

    except ImportError as e:
        # Missing required packages
        missing = str(e)
        print(json.dumps({
            "error": f"Missing dependency: {missing}",
            "hint": (
                "Install required packages: 'pip install requests readability-lxml html2text' "
                "or 'uv pip install requests readability-lxml html2text'"
            ),
        }))
        sys.exit(1)
    except Exception as e:
        # Unrecoverable failure
        print(json.dumps({
            "error": str(e),
            "hint": "Unexpected error during page extraction. Try again or use a different URL.",
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
