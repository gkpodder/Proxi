"""CLI wrapper for extracting web page content.

Exit code contract:
  0 — Script ran to completion. stdout is a JSON object with content/summary.
      If extraction is unsupported for the fetched content type, returns empty
      content with a note (not an error).
  1 — Unrecoverable script failure (bad URL, import error, no network).
      stdout is a JSON object with "error" and "hint" keys.
"""

from __future__ import annotations

import argparse
import json
import sys

_DEFAULT_MAX_CHARS = 10_000
_DEFAULT_CHUNK_SIZE = 5_000
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 ProxiWebExtract/1.0"
)
_HTML_CONTENT_MARKERS = ("text/html", "application/xhtml+xml")
_PDF_CONTENT_MARKERS = ("application/pdf", "application/x-pdf")


def _truncate_at_boundary(content: str, max_chars: int) -> tuple[str, bool, int]:
    if len(content) <= max_chars:
        return content, False, len(content)

    truncated_from_chars = len(content)
    sliced = content[:max_chars]
    boundary = max(sliced.rfind("\n\n"), sliced.rfind("\n"))
    if boundary >= int(max_chars * 0.6):
        sliced = sliced[:boundary].rstrip()
    else:
        sliced = sliced.rstrip()

    sliced += (
        f"\n\n[Content truncated — full article exceeds {max_chars} characters]"
    )
    return sliced, True, truncated_from_chars


def _paginate(content: str, chunk_index: int, chunk_size: int) -> tuple[str, int, bool]:
    if not content:
        return "", 0, False
    total_chunks = max(1, (len(content) + chunk_size - 1) // chunk_size)
    safe_index = max(0, min(chunk_index, total_chunks - 1))
    start = safe_index * chunk_size
    end = min(start + chunk_size, len(content))
    has_more = safe_index < (total_chunks - 1)
    return content[start:end], total_chunks, has_more


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract content from a web page",
        allow_abbrev=False,
    )
    parser.add_argument("--url", required=True, help="Web page URL")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=_DEFAULT_MAX_CHARS,
        help="Maximum characters to return before summarizing (default: 10000)",
    )
    parser.add_argument(
        "--chunk-index",
        type=int,
        default=0,
        help="0-based chunk index when using chunked extraction (default: 0)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        help="Chunk size in characters for paged extraction (optional)",
    )

    args = parser.parse_args()
    max_chars = max(250, args.max_chars)
    chunk_index = max(0, args.chunk_index)
    chunk_size = max(500, args.chunk_size) if args.chunk_size is not None else None

    try:
        import requests
        import html2text
        from readability import Document

        request_headers = {
            "User-Agent": _USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "application/pdf;q=0.8,*/*;q=0.5"
            ),
            "Accept-Language": "en-US,en;q=0.8",
        }

        try:
            response = requests.get(
                args.url,
                timeout=15,
                allow_redirects=True,
                headers=request_headers,
            )
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

        content_type = response.headers.get("Content-Type", "").lower()
        metadata = {
            "url": args.url,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_type": content_type,
            "max_chars": max_chars,
            "chunk_index": chunk_index,
            "chunk_size": chunk_size,
        }

        if any(marker in content_type for marker in _PDF_CONTENT_MARKERS):
            print(json.dumps({
                **metadata,
                "title": "PDF content not extracted",
                "content": "",
                "char_count": 0,
                "is_summarized": False,
                "truncated_from_chars": 0,
                "total_chunks": 0,
                "has_more_chunks": False,
                "unsupported_content_type": True,
                "note": "PDF URL detected. This extractor currently supports HTML pages only.",
            }))
            sys.exit(0)

        if content_type and not any(
            marker in content_type for marker in _HTML_CONTENT_MARKERS
        ):
            print(json.dumps({
                **metadata,
                "title": "Unsupported content type",
                "content": "",
                "char_count": 0,
                "is_summarized": False,
                "truncated_from_chars": 0,
                "total_chunks": 0,
                "has_more_chunks": False,
                "unsupported_content_type": True,
                "note": "Unsupported content type for readability extraction. Use an HTML URL.",
            }))
            sys.exit(0)

        doc = Document(response.text)
        content_html = doc.summary()

        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        markdown_content = h.handle(content_html).strip()

        source_len = len(markdown_content)
        is_summarized = False
        truncated_from_chars = source_len
        total_chunks = 1
        has_more_chunks = False

        if chunk_size is not None:
            markdown_content, total_chunks, has_more_chunks = _paginate(
                markdown_content,
                chunk_index=chunk_index,
                chunk_size=chunk_size or _DEFAULT_CHUNK_SIZE,
            )
        else:
            markdown_content, is_summarized, truncated_from_chars = _truncate_at_boundary(
                markdown_content,
                max_chars=max_chars,
            )

        print(json.dumps({
            **metadata,
            "title": doc.title() or "Untitled",
            "content": markdown_content,
            "char_count": len(markdown_content),
            "is_summarized": is_summarized,
            "truncated_from_chars": truncated_from_chars,
            "total_chunks": total_chunks,
            "has_more_chunks": has_more_chunks,
        }))
        sys.exit(0)

    except ImportError as e:
        print(json.dumps({
            "error": f"Missing dependency: {e}",
            "hint": (
                "Install required packages: 'pip install requests readability-lxml html2text' "
                "or 'uv pip install requests readability-lxml html2text'"
            ),
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "error": str(e),
            "hint": "Unexpected error during page extraction. Try again or use a different URL.",
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
