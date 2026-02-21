"""Notion API tools for MCP server."""

import os
from typing import Any

from dotenv import load_dotenv
from notion_client import Client

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

load_dotenv()


class NotionTools:
    """Tools for interacting with the Notion API."""

    def __init__(self) -> None:
        """Initialize Notion tools with credentials."""
        api_key = os.getenv("NOTION_API_KEY")
        if not api_key:
            raise RuntimeError("NOTION_API_KEY is not set")

        self.parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID")
        if not self.parent_page_id:
            raise RuntimeError("NOTION_PARENT_PAGE_ID is not set")

        self.client = Client(auth=api_key)
        logger.info("notion_authenticated")

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
        results = self.client.blocks.children.list(
            block_id=self.parent_page_id,
            page_size=max_results,
        )
        items = []
        for block in results.get("results", []):
            if block.get("type") == "child_page":
                items.append({
                    "id": block.get("id"),
                    "type": "page",
                    "title": block.get("child_page", {}).get("title", "(Untitled)"),
                })
            elif block.get("type") == "child_database":
                items.append({
                    "id": block.get("id"),
                    "type": "database",
                    "title": block.get("child_database", {}).get("title", "(Untitled)"),
                })
        return {"items": items, "count": len(items)}

    async def create_page(self, title: str, content: str | None = None) -> dict[str, Any]:
        """Create a new page under the parent page."""
        children = []
        if content:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": content}}
                    ]
                },
            })

        page = self.client.pages.create(
            parent={"page_id": self.parent_page_id},
            properties={
                "title": {
                    "title": [
                        {"type": "text", "text": {"content": title}}
                    ]
                }
            },
            children=children,
        )

        return {
            "id": page.get("id"),
            "title": title,
            "url": page.get("url"),
        }

    async def append_to_page(self, page_id: str, content: str) -> dict[str, Any]:
        """Append a paragraph block to a page."""
        result = self.client.blocks.children.append(
            block_id=page_id,
            children=[
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {"type": "text", "text": {"content": content}}
                        ]
                    },
                }
            ],
        )
        return {
            "page_id": page_id,
            "appended": len(result.get("results", []))
        }

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """Get details of a Notion page."""
        page = self.client.pages.retrieve(page_id=page_id)
        return {
            "id": page.get("id"),
            "title": self._extract_title(page.get("properties", {})),
            "url": page.get("url"),
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
        }
