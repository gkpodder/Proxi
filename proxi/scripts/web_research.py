"""CLI wrapper for lightweight multi-step web research.

Exit code contract:
  0 — Script ran to completion. stdout is a JSON research brief.
  1 — Unrecoverable script failure (bad arguments, missing imports, etc).
  3 — Transient search/network failure where retry is likely to succeed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from collections import Counter
from urllib.parse import urlparse, urlunparse

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 ProxiWebResearch/1.0"
)
_DEFAULT_MAX_SOURCES = 6
_MAX_SOURCES_LIMIT = 12
_PRICE_PATTERN = re.compile(r"\$\s?(\d{1,4}(?:[.,]\d{2})?)")


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    normalized = parsed._replace(query="", fragment="")
    return urlunparse(normalized)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_transient_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = (
        "timeout",
        "temporarily unavailable",
        "too many requests",
        "rate limit",
        "connection reset",
        "connection error",
        "service unavailable",
        "dns",
    )
    return any(marker in message for marker in markers)


def _query_variants(query: str, depth: str, shopping_mode: bool) -> list[str]:
    base = query.strip()
    variants = [base]
    if depth in {"balanced", "deep"}:
        variants.append(f"{base} key facts")
        variants.append(f"{base} recent updates")
    if depth == "deep":
        variants.append(f"{base} expert analysis")
        variants.append(f"{base} common misconceptions")
    if shopping_mode:
        variants.append(f"{base} best price")
        variants.append(f"{base} deals discount")

    deduped: list[str] = []
    for item in variants:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _extractive_points(content: str, max_points: int = 2) -> list[str]:
    if not content:
        return []
    normalized = content.replace("\r", "")
    lines = [line.strip(" -*#") for line in normalized.splitlines()]
    candidates = [line for line in lines if len(line) >= 50 and "http" not in line]
    return candidates[:max_points]


def _search_web(
    query: str,
    region: str | None,
    max_results: int,
) -> list[dict[str, str]]:
    from ddgs import DDGS

    results: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for rank, result in enumerate(
            ddgs.text(
                query,
                region=region,
                safesearch="moderate",
                timelimit=None,
                max_results=max_results,
            ),
            start=1,
        ):
            url = result.get("href", "")
            results.append({
                "title": result.get("title", ""),
                "url": url,
                "description": result.get("body", ""),
                "domain": _domain(url),
                "rank": rank,
                "query": query,
            })
    return results


def _extract_url(url: str, max_chars: int = 5000) -> dict[str, str | int | bool]:
    import requests
    import html2text
    from readability import Document

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.8",
    }
    response = requests.get(url, timeout=15, allow_redirects=True, headers=headers)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return {
            "url": url,
            "final_url": response.url,
            "content_type": content_type,
            "title": "",
            "content": "",
            "ok": False,
            "reason": "unsupported_content_type",
        }

    doc = Document(response.text)
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    markdown = converter.handle(doc.summary()).strip()
    if len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip() + "\n\n[Content truncated]"

    return {
        "url": url,
        "final_url": response.url,
        "content_type": content_type,
        "title": doc.title() or "Untitled",
        "content": markdown,
        "ok": True,
    }


def _price_candidates(*texts: str) -> list[float]:
    prices: list[float] = []
    for text in texts:
        if not text:
            continue
        for match in _PRICE_PATTERN.findall(text):
            cleaned = match.replace(",", "")
            try:
                prices.append(float(cleaned))
            except ValueError:
                continue
    return prices


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run lightweight web research over multiple sources",
        allow_abbrev=False,
    )
    parser.add_argument("--query", required=True, help="Research query")
    parser.add_argument(
        "--depth",
        choices=["quick", "balanced", "deep"],
        default="balanced",
        help="Research depth (default: balanced)",
    )
    parser.add_argument(
        "--max-sources",
        type=int,
        default=_DEFAULT_MAX_SOURCES,
        help="Max number of extracted sources to include (default: 6, max: 12)",
    )
    parser.add_argument(
        "--region",
        help="Search region hint (e.g., us-en)",
    )
    parser.add_argument(
        "--include-domains",
        action="append",
        default=[],
        help="Allowed domains (can be repeated)",
    )
    parser.add_argument(
        "--exclude-domains",
        action="append",
        default=[],
        help="Blocked domains (can be repeated)",
    )
    parser.add_argument(
        "--shopping-mode",
        action="store_true",
        help="Enable best-effort price/deal extraction mode",
    )
    parser.add_argument(
        "--product-query",
        help="Optional product query override when shopping mode is enabled",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        help="Optional max price filter used in shopping mode",
    )

    args = parser.parse_args()
    max_sources = max(1, min(args.max_sources, _MAX_SOURCES_LIMIT))
    include_domains = {item.lower() for item in args.include_domains if item}
    exclude_domains = {item.lower() for item in args.exclude_domains if item}

    base_query = args.product_query.strip() if (args.shopping_mode and args.product_query) else args.query.strip()
    variants = _query_variants(base_query, args.depth, args.shopping_mode)

    depth_to_search_limit = {"quick": 4, "balanced": 6, "deep": 8}
    search_limit = depth_to_search_limit[args.depth]
    depth_to_workers = {"quick": 2, "balanced": 3, "deep": 4}
    workers = depth_to_workers[args.depth]

    try:
        all_results: list[dict[str, str]] = []
        for query in variants:
            all_results.extend(
                _search_web(
                    query=query,
                    region=args.region,
                    max_results=search_limit,
                )
            )

        deduped_candidates: list[dict[str, str]] = []
        seen: set[str] = set()
        for result in all_results:
            url = result["url"]
            if not url:
                continue
            domain = result["domain"]
            if include_domains and domain not in include_domains:
                continue
            if domain in exclude_domains:
                continue
            canonical = _canonicalize_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            deduped_candidates.append(result)
            if len(deduped_candidates) >= max_sources * 2:
                break

        extracted: list[dict[str, str | int | bool]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_extract_url, item["url"]) for item in deduped_candidates]
            for future in concurrent.futures.as_completed(futures):
                try:
                    payload = future.result()
                    extracted.append(payload)
                except Exception:
                    continue
                if len(extracted) >= max_sources:
                    break

        final_sources: list[dict[str, str | int | float | list[str]]] = []
        key_points: list[str] = []
        domain_counter: Counter[str] = Counter()
        deals: list[dict[str, str | float]] = []

        for item in deduped_candidates:
            url = item["url"]
            match = next((entry for entry in extracted if entry.get("url") == url), None)
            if not match or not match.get("ok"):
                continue

            points = _extractive_points(str(match.get("content", "")), max_points=2)
            domain = str(item["domain"])
            domain_counter[domain] += 1
            source_payload = {
                "title": str(match.get("title", item.get("title", "Untitled"))),
                "url": str(match.get("final_url", url)),
                "domain": domain,
                "query": str(item.get("query", "")),
                "description": str(item.get("description", "")),
                "key_evidence": points[:2],
            }
            final_sources.append(source_payload)
            for point in points:
                if point not in key_points:
                    key_points.append(point)

            if args.shopping_mode:
                prices = _price_candidates(
                    str(item.get("description", "")),
                    str(match.get("content", ""))[:1200],
                )
                for price in sorted(set(prices)):
                    if args.max_price is not None and price > args.max_price:
                        continue
                    deals.append({
                        "source": str(match.get("final_url", url)),
                        "title": str(match.get("title", item.get("title", ""))),
                        "price": price,
                    })

            if len(final_sources) >= max_sources:
                break

        key_points = key_points[:8]
        top_domains = [domain for domain, _ in domain_counter.most_common(5)]
        summary = (
            f"Reviewed {len(final_sources)} sources across {len(top_domains)} domains "
            f"for '{base_query}'."
        )
        if not final_sources:
            summary = (
                f"No extractable sources were found for '{base_query}'. "
                "Try different keywords or loosen domain filters."
            )

        gaps_or_uncertainties: list[str] = []
        if len(final_sources) < min(3, max_sources):
            gaps_or_uncertainties.append(
                "Limited source coverage; confidence is moderate-to-low."
            )
        if args.shopping_mode and not deals:
            gaps_or_uncertainties.append(
                "No clear price snippets found in fetched pages."
            )

        next_queries = [
            f"{base_query} latest 2026 update",
            f"{base_query} primary sources",
        ]
        if args.shopping_mode:
            next_queries.append(f"{base_query} coupon code")

        output: dict[str, object] = {
            "query": base_query,
            "depth": args.depth,
            "summary": summary,
            "key_points": key_points,
            "sources": final_sources,
            "top_domains": top_domains,
            "gaps_or_uncertainties": gaps_or_uncertainties,
            "next_queries": next_queries,
            "candidate_count": len(deduped_candidates),
            "source_count": len(final_sources),
        }
        if args.shopping_mode:
            output["shopping_mode"] = True
            output["deals"] = sorted(deals, key=lambda d: float(d["price"]))[:10]
            output["deal_count"] = len(output["deals"])
            output["price_freshness_note"] = (
                "Prices are best-effort snippets from public pages and may be stale."
            )

        print(json.dumps(output))
        sys.exit(0)
    except ImportError as e:
        print(json.dumps({
            "error": f"Missing dependency: {e}",
            "hint": "Install required packages (ddgs, requests, readability-lxml, html2text).",
        }))
        sys.exit(1)
    except Exception as e:
        if _is_transient_error(e):
            print(json.dumps({
                "error": str(e),
                "hint": "Transient web/search failure. Retrying may succeed.",
                "transient": True,
            }))
            sys.exit(3)
        print(json.dumps({
            "error": str(e),
            "hint": "Unexpected failure while running web research.",
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
