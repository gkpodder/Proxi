#!/usr/bin/env python3
"""Combined MCP Server for Gmail and Notion."""

import asyncio
import json
import sys
from typing import Any

from proxi.mcp.servers.gmail_tools import GmailTools
from proxi.mcp.servers.notion_tools import NotionTools
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class CombinedMCPServer:
    """MCP server for Gmail and Notion operations."""

    def __init__(self) -> None:
        """Initialize the combined MCP server."""
        self._gmail: GmailTools | None = None
        self._notion: NotionTools | None = None

    def _get_gmail(self) -> GmailTools:
        """Lazily initialize Gmail tools to avoid blocking initialize."""
        if self._gmail is None:
            self._gmail = GmailTools()
        return self._gmail

    def _get_notion(self) -> NotionTools:
        """Lazily initialize Notion tools to avoid blocking initialize."""
        if self._notion is None:
            self._notion = NotionTools()
        return self._notion

    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {
                "name": "proxi-mcp",
                "version": "1.0.0",
            },
        }

    async def handle_tools_list(self) -> dict[str, Any]:
        """Handle tools/list request."""
        return {
            "tools": [
                {
                    "name": "read_emails",
                    "description": "Read emails from Gmail inbox",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of emails to retrieve (default: 10)",
                            },
                            "query": {
                                "type": "string",
                                "description": "Gmail search query (e.g., 'from:sender@example.com')",
                            },
                        },
                        "required": [],
                    },
                },
                {
                    "name": "send_email",
                    "description": "Send an email via Gmail",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address"},
                            "subject": {"type": "string", "description": "Email subject"},
                            "body": {"type": "string", "description": "Email body (plain text or HTML)"},
                            "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
                            "bcc": {"type": "string", "description": "BCC recipients (comma-separated)"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
                {
                    "name": "get_email",
                    "description": "Get details of a specific email",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "email_id": {
                                "type": "string",
                                "description": "Gmail message ID",
                            }
                        },
                        "required": ["email_id"],
                    },
                },
                {
                    "name": "notion_list_children",
                    "description": "List child pages/databases under the configured parent page",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of items to retrieve (default: 10)",
                            }
                        },
                        "required": [],
                    },
                },
                {
                    "name": "notion_create_page",
                    "description": "Create a new Notion page under the configured parent page",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Page title"},
                            "content": {"type": "string", "description": "Optional page content"},
                        },
                        "required": ["title"],
                    },
                },
                {
                    "name": "notion_append_to_page",
                    "description": "Append a paragraph to an existing Notion page",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Notion page ID"},
                            "content": {"type": "string", "description": "Content to append"},
                        },
                        "required": ["page_id", "content"],
                    },
                },
                {
                    "name": "notion_get_page",
                    "description": "Get details for a Notion page",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Notion page ID"},
                        },
                        "required": ["page_id"],
                    },
                },
            ]
        }

    async def handle_call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        try:
            if name == "read_emails":
                max_results = arguments.get("max_results", 10)
                query = arguments.get("query", "")
                result = await self._get_gmail().read_emails(max_results, query)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "send_email":
                to = arguments.get("to")
                subject = arguments.get("subject")
                body = arguments.get("body")
                cc = arguments.get("cc")
                bcc = arguments.get("bcc")
                result = await self._get_gmail().send_email(to, subject, body, cc, bcc)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "get_email":
                email_id = arguments.get("email_id")
                result = await self._get_gmail().get_email(email_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_list_children":
                max_results = arguments.get("max_results", 10)
                result = await self._get_notion().list_children(max_results)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_create_page":
                title = arguments.get("title")
                content = arguments.get("content")
                result = await self._get_notion().create_page(title, content)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_append_to_page":
                page_id = arguments.get("page_id")
                content = arguments.get("content")
                result = await self._get_notion().append_to_page(page_id, content)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            if name == "notion_get_page":
                page_id = arguments.get("page_id")
                result = await self._get_notion().get_page(page_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

        except Exception as e:
            logger.error("combined_tool_error", tool=name, error=str(e))
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    async def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process an incoming JSON-RPC message."""
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list()
            elif method == "tools/call":
                result = await self.handle_call_tool(
                    params.get("name"), params.get("arguments", {})
                )
            elif method == "notifications/initialized":
                return None
            else:
                result = {"error": f"Unknown method: {method}"}

            if msg_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result,
                }
        except Exception as e:
            logger.error("message_processing_error", error=str(e))
            if msg_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}",
                    },
                }
        return None

    def run(self) -> None:
        """Run the MCP server (synchronous version for stdio)."""
        logger.info("combined_mcp_server_started")

        try:
            while True:
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break

                    message = json.loads(line.strip())
                    response = asyncio.run(self.process_message(message))
                    if response:
                        sys.stdout.write(json.dumps(response) + "\n")
                        sys.stdout.flush()
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error("server_error", error=str(e))

        except KeyboardInterrupt:
            logger.info("combined_mcp_server_stopped")
        except Exception as e:
            logger.error("combined_mcp_fatal_error", error=str(e))
            sys.exit(1)


if __name__ == "__main__":
    server = CombinedMCPServer()
    server.run()
