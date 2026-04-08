from __future__ import annotations

import json
import sys
import types
from io import StringIO
from contextlib import redirect_stdout

import pytest

from proxi.scripts import web_extract, web_research, web_search


def _run_main(main_fn, argv: list[str]) -> tuple[int, dict]:
    old_argv = sys.argv[:]
    stream = StringIO()
    try:
        sys.argv = argv
        with redirect_stdout(stream):
            with pytest.raises(SystemExit) as exited:
                main_fn()
        payload = json.loads(stream.getvalue().strip())
        return int(exited.value.code), payload
    finally:
        sys.argv = old_argv


def test_web_search_enforces_bounds_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, query, max_results, region=None, safesearch=None, timelimit=None):
            seen.update({
                "query": query,
                "max_results": max_results,
                "region": region,
                "safesearch": safesearch,
                "timelimit": timelimit,
            })
            return [
                {
                    "title": "Doc",
                    "href": "https://example.com/path?q=1",
                    "body": "A description",
                }
            ]

    fake_ddgs_module = types.SimpleNamespace(DDGS=FakeDDGS)
    monkeypatch.setitem(sys.modules, "ddgs", fake_ddgs_module)

    code, payload = _run_main(
        web_search.main,
        [
            "web_search.py",
            "--query=python testing",
            "--max-results=100",
            "--site=example.com",
            "--region=us-en",
            "--time-limit=w",
        ],
    )

    assert code == 0
    assert payload["max_results"] == 20
    assert payload["count"] == 1
    assert payload["results"][0]["source_domain"] == "example.com"
    assert seen["query"] == "python testing site:example.com"
    assert seen["region"] == "us-en"
    assert seen["timelimit"] == "w"


def test_web_search_transient_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, *args, **kwargs):
            raise TimeoutError("request timeout")

    fake_ddgs_module = types.SimpleNamespace(DDGS=FakeDDGS)
    monkeypatch.setitem(sys.modules, "ddgs", fake_ddgs_module)

    code, payload = _run_main(web_search.main, ["web_search.py", "--query=test"])
    assert code == 3
    assert payload["transient"] is True


def test_web_extract_reports_pdf_as_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    class Timeout(Exception):
        pass

    class RequestException(Exception):
        pass

    class FakeResponse:
        status_code = 200
        url = "https://example.com/file.pdf"
        text = "pdf bytes"
        headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self) -> None:
            return None

    fake_requests = types.SimpleNamespace(
        get=lambda *args, **kwargs: FakeResponse(),
        exceptions=types.SimpleNamespace(
            Timeout=Timeout,
            RequestException=RequestException,
        ),
    )
    fake_readability = types.SimpleNamespace(Document=lambda text: None)
    fake_html2text = types.SimpleNamespace(HTML2Text=lambda: None)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setitem(sys.modules, "readability", fake_readability)
    monkeypatch.setitem(sys.modules, "html2text", fake_html2text)

    code, payload = _run_main(web_extract.main, ["web_extract.py", "--url=https://example.com/file.pdf"])
    assert code == 0
    assert payload["unsupported_content_type"] is True
    assert payload["content"] == ""
    assert "pdf" in payload["note"].lower()


def test_web_extract_chunked_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Timeout(Exception):
        pass

    class RequestException(Exception):
        pass

    class FakeResponse:
        status_code = 200
        url = "https://example.com/article"
        text = "<html></html>"
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def raise_for_status(self) -> None:
            return None

    class FakeDocument:
        def __init__(self, text: str) -> None:
            self.text = text

        def summary(self) -> str:
            return "<div>ignored</div>"

        def title(self) -> str:
            return "Article"

    class FakeConverter:
        ignore_links = False
        ignore_images = False

        def handle(self, html: str) -> str:
            return "A" * 1300

    fake_requests = types.SimpleNamespace(
        get=lambda *args, **kwargs: FakeResponse(),
        exceptions=types.SimpleNamespace(
            Timeout=Timeout,
            RequestException=RequestException,
        ),
    )
    fake_readability = types.SimpleNamespace(Document=FakeDocument)
    fake_html2text = types.SimpleNamespace(HTML2Text=FakeConverter)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setitem(sys.modules, "readability", fake_readability)
    monkeypatch.setitem(sys.modules, "html2text", fake_html2text)

    code, payload = _run_main(
        web_extract.main,
        [
            "web_extract.py",
            "--url=https://example.com/article",
            "--chunk-size=500",
            "--chunk-index=1",
        ],
    )
    assert code == 0
    assert payload["total_chunks"] == 3
    assert payload["has_more_chunks"] is True
    assert payload["char_count"] == 500


def test_web_research_shapes_output_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search_web(query: str, region: str | None, max_results: int):
        return [
            {
                "title": "A",
                "url": "https://example.com/a?x=1",
                "description": "desc A",
                "domain": "example.com",
                "rank": 1,
                "query": query,
            },
            {
                "title": "A dup",
                "url": "https://example.com/a?x=2",
                "description": "desc dup",
                "domain": "example.com",
                "rank": 2,
                "query": query,
            },
            {
                "title": "B",
                "url": "https://other.com/b",
                "description": "desc B",
                "domain": "other.com",
                "rank": 3,
                "query": query,
            },
        ]

    def fake_extract(url: str, max_chars: int = 5000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "title": "Title",
            "content": (
                "This is a useful evidence line that is definitely longer than fifty "
                "characters for extraction."
            ),
            "ok": True,
        }

    monkeypatch.setattr(web_research, "_search_web", fake_search_web)
    monkeypatch.setattr(web_research, "_extract_url", fake_extract)

    code, payload = _run_main(
        web_research.main,
        [
            "web_research.py",
            "--query=ai agent frameworks",
            "--depth=quick",
            "--max-sources=3",
        ],
    )
    assert code == 0
    assert payload["source_count"] == 2
    assert payload["candidate_count"] == 2
    assert payload["summary"]
    assert payload["key_points"]
    assert len(payload["sources"]) == 2


def test_web_research_shopping_mode_returns_deals(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search_web(query: str, region: str | None, max_results: int):
        return [
            {
                "title": "Deal listing",
                "url": "https://shop.example.com/item",
                "description": "Now $29.99 limited stock",
                "domain": "shop.example.com",
                "rank": 1,
                "query": query,
            }
        ]

    def fake_extract(url: str, max_chars: int = 5000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "title": "Item",
            "content": "Price options include $24.99 and $39.99",
            "ok": True,
        }

    monkeypatch.setattr(web_research, "_search_web", fake_search_web)
    monkeypatch.setattr(web_research, "_extract_url", fake_extract)

    code, payload = _run_main(
        web_research.main,
        [
            "web_research.py",
            "--query=headphones",
            "--shopping-mode",
            "--max-price=30",
        ],
    )
    assert code == 0
    assert payload["shopping_mode"] is True
    assert payload["deal_count"] >= 1
    assert all(item["price"] <= 30 for item in payload["deals"])
