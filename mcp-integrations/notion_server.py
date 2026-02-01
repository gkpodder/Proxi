import os
import re
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from notion_client import Client
from mcp.server.fastmcp import FastMCP

load_dotenv()

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.logger import setup_logger

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
logger = setup_logger("MCPIntegrations", log_dir=LOG_DIR)


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if not value and default is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return value or default or ""


def get_notion_client() -> Client:
    """Get Notion client with API token."""
    token = _get_env("NOTION_API_KEY")
    logger.info("Initializing Notion client")
    return Client(auth=token)


def _normalize_page_id(page_id: str) -> str:
    """Normalize Notion page ID (strip URL and non-hex chars)."""
    if not page_id:
        return ""
    if "notion.so" in page_id:
        page_id = page_id.split("/")[-1].split("?")[0]
    return re.sub(r"[^0-9a-fA-F]", "", page_id)


mcp = FastMCP("notion")


@mcp.tool()
def notion_search_pages(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Search Notion pages by title or content."""
    client = get_notion_client()
    logger.info("notion_search_pages query=%s max_results=%s", query, max_results)
    results = client.search(
        query=query,
        sort={"direction": "descending", "timestamp": "last_edited_time"},
        page_size=max_results,
    )
    
    pages = []
    for result in results.get("results", []):
        if result["object"] == "page":
            pages.append({
                "id": result["id"],
                "title": _extract_title(result),
                "created_time": result.get("created_time"),
                "last_edited_time": result.get("last_edited_time"),
            })
    return pages


@mcp.tool()
def notion_get_page(page_id: str) -> Dict[str, Any]:
    """Get page content from Notion."""
    client = get_notion_client()
    logger.info("notion_get_page id=%s", page_id)
    page = client.pages.retrieve(page_id)
    blocks = client.blocks.children.list(page_id)
    
    content = []
    for block in blocks.get("results", []):
        block_text = _extract_block_text(block)
        if block_text:
            content.append(block_text)
    
    return {
        "id": page["id"],
        "title": _extract_title(page),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "content": "\n".join(content),
    }


@mcp.tool()
def notion_create_page(
    database_id: str = "",
    title: str = "",
    content: str = "",
    parent_page_id: str = "",
) -> Dict[str, Any]:
    """Create a new page in a Notion database or under a parent page."""
    client = get_notion_client()
    logger.info("notion_create_page title=%s", title)

    db_id = database_id or os.getenv("NOTION_DEFAULT_DATABASE_ID", "")
    page_id = parent_page_id or os.getenv("NOTION_PARENT_PAGE_ID", "")
    page_id = _normalize_page_id(page_id)

    if not db_id and not page_id:
        raise RuntimeError(
            "Missing parent. Provide database_id or parent_page_id, or set NOTION_DEFAULT_DATABASE_ID / NOTION_PARENT_PAGE_ID in .env."
        )

    parent = {"database_id": db_id} if db_id else {"page_id": page_id}

    logger.info("Calling Notion API: pages.create")
    new_page = client.pages.create(
        parent=parent,
        properties={
            "title": {
                "id": "title",
                "type": "title",
                "title": [{"type": "text", "text": {"content": title}}],
            }
        },
        children=[
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                },
            }
        ],
    )

    return {
        "id": new_page["id"],
        "title": title,
        "created_time": new_page.get("created_time"),
    }


@mcp.tool()
def notion_update_page(page_id: str, content: str) -> Dict[str, Any]:
    """Update page content in Notion."""
    client = get_notion_client()

    logger.info("notion_update_page id=%s", page_id)

    page_id = _normalize_page_id(page_id)
    if not page_id:
        raise RuntimeError("Invalid page_id. Provide a valid Notion page ID or URL.")
    
    # Clear existing blocks
    logger.info("Calling Notion API: blocks.children.list")
    blocks = client.blocks.children.list(page_id)
    for block in blocks.get("results", []):
        logger.info("Calling Notion API: blocks.delete id=%s", block.get("id"))
        client.blocks.delete(block["id"])
    
    # Add new content
    logger.info("Calling Notion API: blocks.children.append")
    client.blocks.children.append(
        page_id,
        children=[
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            }
        ]
    )
    
    return {"id": page_id, "status": "updated"}


@mcp.tool()
def notion_list_databases() -> List[Dict[str, Any]]:
    """List all Notion databases."""
    client = get_notion_client()
    
    # Search for databases (data_source in Notion API)
    logger.info("Calling Notion API: search for data_source")
    results = client.search(filter={"value": "data_source", "property": "object"})
    
    databases = []
    for result in results.get("results", []):
        if result["object"] == "database":
            databases.append({
                "id": result["id"],
                "title": _extract_title(result),
                "created_time": result.get("created_time"),
            })
    return databases


def _extract_title(obj: Dict[str, Any]) -> str:
    """Extract title from Notion object."""
    if "properties" in obj and "title" in obj["properties"]:
        title_prop = obj["properties"]["title"]
        if title_prop.get("type") == "title" and title_prop.get("title"):
            return "".join(t.get("plain_text", "") for t in title_prop["title"])
    if "title" in obj:
        return "".join(t.get("plain_text", "") for t in obj["title"])
    return "Untitled"


def _extract_block_text(block: Dict[str, Any]) -> str:
    """Extract text from Notion block."""
    block_type = block.get("type")
    
    if block_type in ("paragraph", "heading_1", "heading_2", "heading_3"):
        text_obj = block[block_type]
        return "".join(t.get("plain_text", "") for t in text_obj.get("rich_text", []))
    elif block_type == "bulleted_list_item":
        text_obj = block["bulleted_list_item"]
        return "• " + "".join(t.get("plain_text", "") for t in text_obj.get("rich_text", []))
    elif block_type == "numbered_list_item":
        text_obj = block["numbered_list_item"]
        return "1. " + "".join(t.get("plain_text", "") for t in text_obj.get("rich_text", []))
    
    return ""


if __name__ == "__main__":
    mcp.run()
