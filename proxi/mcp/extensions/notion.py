"""Notion MCP integration using MCP protocol."""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from notion_client import Client

load_dotenv()


def _get_env(name: str, default: Optional[str] = None) -> str:
    """Get environment variable with optional default."""
    value = os.getenv(name, default)
    if not value and default is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return value or default or ""


def get_notion_client() -> Client:
    """Get Notion client with API token."""
    token = _get_env("NOTION_API_KEY")
    return Client(auth=token)


def _normalize_page_id(page_id: str) -> str:
    """Normalize Notion page ID (strip URL and non-hex chars)."""
    if not page_id:
        return ""
    if "notion.so" in page_id:
        page_id = page_id.split("/")[-1].split("?")[0]
    return re.sub(r"[^0-9a-fA-F\-]", "", page_id)


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


# MCP Protocol Implementation
def _send_response(response: Dict[str, Any]) -> None:
    """Send a JSON-RPC response."""
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _send_error(request_id: int, code: int, message: str) -> None:
    """Send a JSON-RPC error response."""
    _send_response({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message
        }
    })


def _handle_initialize(request_id: int) -> None:
    """Handle MCP initialize request."""
    _send_response({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "notion",
                "version": "1.0.0"
            }
        }
    })


def _handle_list_tools(request_id: int) -> None:
    """Handle MCP list_tools request."""
    tools = [
        {
            "name": "notion_search_pages",
            "description": "Search Notion pages by title or content.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "notion_get_page",
            "description": "Get page content from Notion.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "Notion page ID or URL"
                    }
                },
                "required": ["page_id"]
            }
        },
        {
            "name": "notion_create_page",
            "description": "Create a new page in a Notion database or under a parent page.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Page title"
                    },
                    "content": {
                        "type": "string",
                        "description": "Page content"
                    },
                    "database_id": {
                        "type": "string",
                        "description": "Target database ID (optional, uses default if not provided)"
                    },
                    "parent_page_id": {
                        "type": "string",
                        "description": "Parent page ID (optional)"
                    }
                },
                "required": ["title"]
            }
        },
        {
            "name": "notion_update_page",
            "description": "Update page content in Notion.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "Notion page ID or URL"
                    },
                    "content": {
                        "type": "string",
                        "description": "New page content"
                    }
                },
                "required": ["page_id", "content"]
            }
        },
        {
            "name": "notion_list_databases",
            "description": "List all Notion databases.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        }
    ]
    
    _send_response({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "tools": tools
        }
    })


def _handle_call_tool(request_id: int, tool_name: str, arguments: Dict[str, Any]) -> None:
    """Handle MCP call_tool request."""
    try:
        if tool_name == "notion_search_pages":
            result = _tool_notion_search_pages(arguments)
        elif tool_name == "notion_get_page":
            result = _tool_notion_get_page(arguments)
        elif tool_name == "notion_create_page":
            result = _tool_notion_create_page(arguments)
        elif tool_name == "notion_update_page":
            result = _tool_notion_update_page(arguments)
        elif tool_name == "notion_list_databases":
            result = _tool_notion_list_databases(arguments)
        else:
            _send_error(request_id, -32601, f"Unknown tool: {tool_name}")
            return
        
        _send_response({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }
        })
    except Exception as e:
        _send_error(request_id, -32603, f"Tool error: {str(e)}")


def _tool_notion_search_pages(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search Notion pages."""
    query = args.get("query", "")
    max_results = args.get("max_results", 10)
    
    client = get_notion_client()
    
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
    
    return {"pages": pages}


def _tool_notion_get_page(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get page content."""
    page_id = args.get("page_id", "")
    page_id = _normalize_page_id(page_id)
    
    client = get_notion_client()
    
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


def _tool_notion_create_page(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new page."""
    database_id = args.get("database_id", "")
    title = args.get("title", "")
    content = args.get("content", "")
    parent_page_id = args.get("parent_page_id", "")
    
    client = get_notion_client()
    
    db_id = database_id or os.getenv("NOTION_DEFAULT_DATABASE_ID", "")
    page_id = parent_page_id or os.getenv("NOTION_PARENT_PAGE_ID", "")
    page_id = _normalize_page_id(page_id)
    
    if not db_id and not page_id:
        raise RuntimeError(
            "Missing parent. Provide database_id or parent_page_id, or set NOTION_DEFAULT_DATABASE_ID / NOTION_PARENT_PAGE_ID in .env."
        )
    
    parent = {"database_id": db_id} if db_id else {"page_id": page_id}
    
    new_page = client.pages.create(
        parent=parent,
        properties={
            "title": [{"type": "text", "text": {"content": title}}]
        },
        children=[
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                },
            }
        ] if content else [],
    )
    
    return {
        "id": new_page["id"],
        "title": title,
        "created_time": new_page.get("created_time"),
    }


def _tool_notion_update_page(args: Dict[str, Any]) -> Dict[str, Any]:
    """Update page content."""
    page_id = args.get("page_id", "")
    content = args.get("content", "")
    
    page_id = _normalize_page_id(page_id)
    
    if not page_id:
        raise RuntimeError("Invalid page_id. Provide a valid Notion page ID or URL.")
    
    client = get_notion_client()
    
    # Clear existing blocks
    blocks = client.blocks.children.list(page_id)
    for block in blocks.get("results", []):
        client.blocks.delete(block["id"])
    
    # Add new content
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


def _tool_notion_list_databases(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all databases."""
    client = get_notion_client()
    
    results = client.search(filter={"value": "database", "property": "object"})
    
    databases = []
    for result in results.get("results", []):
        if result["object"] == "database":
            databases.append({
                "id": result["id"],
                "title": _extract_title(result),
                "created_time": result.get("created_time"),
            })
    
    return {"databases": databases}


def main():
    """Main MCP server loop."""
    # Use simple stderr logging to avoid blocking
    print("Notion MCP server started", file=sys.stderr, flush=True)
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            
            if method == "initialize":
                _handle_initialize(request_id)
            elif method == "tools/list":
                _handle_list_tools(request_id)
            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                _handle_call_tool(request_id, tool_name, arguments)
            else:
                _send_error(request_id, -32601, f"Unknown method: {method}")
                
        except json.JSONDecodeError:
            continue
        except Exception as e:
            # Log errors but don't block
            print(f"Error: {str(e)}", file=sys.stderr, flush=True)
            continue


if __name__ == "__main__":
    main()
