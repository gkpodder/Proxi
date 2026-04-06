"""Notion API tools for MCP server."""

import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

load_dotenv()


class NotionTools:
    """Tools for interacting with the Notion API."""

    BASE_URL = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self) -> None:
        """Initialize Notion tools with credentials."""
        self.api_key = os.getenv("NOTION_API_KEY")
        if not self.api_key:
            raise RuntimeError("NOTION_API_KEY is not set")

        self.parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID")
        if not self.parent_page_id:
            raise RuntimeError("NOTION_PARENT_PAGE_ID is not set")

        logger.info("notion_authenticated")

    def _http_request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        """Execute a Notion API request and parse JSON response."""
        endpoint = f"{self.BASE_URL}{path}"
        if query:
            endpoint = f"{endpoint}?{urlencode(query)}"

        data = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.NOTION_VERSION,
            "Content-Type": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = Request(endpoint, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=20) as response:  # nosec B310
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as e:
            try:
                body = e.read().decode("utf-8")
                details = json.loads(body)
                message = details.get("message") or str(e)
            except Exception:
                message = str(e)
            raise RuntimeError(f"Notion API error: {message}") from e

    def _extract_title(self, properties: dict[str, Any]) -> str:
        """Extract title from Notion page properties."""
        for prop in properties.values():
            if prop.get("type") == "title":
                title_items = prop.get("title", [])
                if title_items:
                    return "".join(item.get("plain_text", "") for item in title_items)
        return "(Untitled)"

    async def list_children(self, max_results: int = 10) -> dict[str, Any]:
        """List child pages/databases under the parent page."""
        try:
            limit = max(1, min(int(max_results), 100))
            results = self._http_request_json(
                "GET",
                f"/blocks/{self.parent_page_id}/children",
                query={"page_size": limit},
            )
            items = []
            for block in results.get("results", []):
                if block.get("type") == "child_page":
                    items.append(
                        {
                            "id": block.get("id"),
                            "type": "page",
                            "title": block.get("child_page", {}).get("title", "(Untitled)"),
                        }
                    )
                elif block.get("type") == "child_database":
                    items.append(
                        {
                            "id": block.get("id"),
                            "type": "database",
                            "title": block.get("child_database", {}).get("title", "(Untitled)"),
                        }
                    )
            return {"items": items, "count": len(items)}
        except Exception as e:
            logger.error("notion_list_children_error", error=str(e))
            return {"error": str(e)}

    async def create_page(self, title: str, content: str | None = None) -> dict[str, Any]:
        """Create a new page under the parent page."""
        try:
            children = []
            if content:
                children.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": content}}]
                        },
                    }
                )

            safe_title = (title or "").strip() or "Untitled"
            page = self._http_request_json(
                "POST",
                "/pages",
                payload={
                    "parent": {"page_id": self.parent_page_id},
                    "properties": {
                        "title": {
                            "title": [{"type": "text", "text": {"content": safe_title}}]
                        }
                    },
                    "children": children,
                },
            )

            return {
                "id": page.get("id"),
                "title": safe_title,
                "url": page.get("url"),
            }
        except Exception as e:
            logger.error("notion_create_page_error", error=str(e), title=title)
            return {"error": str(e)}

    async def append_to_page(self, page_id: str, content: str) -> dict[str, Any]:
        """Append a paragraph block to a page."""
        try:
            normalized_page_id = (page_id or "").strip()
            if not normalized_page_id:
                return {"error": "page_id cannot be empty"}

            result = self._http_request_json(
                "PATCH",
                f"/blocks/{normalized_page_id}/children",
                payload={
                    "children": [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"type": "text", "text": {"content": content}}]
                            },
                        }
                    ]
                },
            )
            return {
                "page_id": normalized_page_id,
                "appended": len(result.get("results", [])),
            }
        except Exception as e:
            logger.error("notion_append_page_error", error=str(e), page_id=page_id)
            return {"error": str(e)}

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """Get details of a Notion page."""
        try:
            normalized_page_id = (page_id or "").strip()
            if not normalized_page_id:
                return {"error": "page_id cannot be empty"}

            page = self._http_request_json("GET", f"/pages/{normalized_page_id}")
            return {
                "id": page.get("id"),
                "title": self._extract_title(page.get("properties", {})),
                "url": page.get("url"),
                "created_time": page.get("created_time"),
                "last_edited_time": page.get("last_edited_time"),
            }
        except Exception as e:
            logger.error("notion_get_page_error", error=str(e), page_id=page_id)
            return {"error": str(e)}
