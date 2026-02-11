"""Gmail integration for MCP server."""

import os
import base64
from typing import Any
from email.mime.text import MIMEText

from proxi.mcp.servers.integrations.base import BaseIntegration


class GmailIntegration(BaseIntegration):
    """Gmail integration providing email tools."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize Gmail integration."""
        super().__init__(config)
        self.service = None
        self.credentials = None
        self._initialized = False

    def get_name(self) -> str:
        """Get the integration name."""
        return "gmail"

    async def initialize(self) -> None:
        """Initialize Gmail API connection."""
        if self._initialized:
            return
            
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise RuntimeError(
                "Gmail integration requires google-auth, google-auth-oauthlib, "
                "google-auth-httplib2, and google-api-python-client. "
                "Install with: pip install google-auth google-auth-oauthlib "
                "google-auth-httplib2 google-api-python-client"
            )

        # If modifying these scopes, delete the token.json file.
        SCOPES = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.modify",
        ]

        creds = None
        # Token file stores user's access and refresh tokens
        token_path = self.config.get("token_path") or os.getenv("GMAIL_TOKEN_PATH", "gmail_token.json")
        credentials_path = self.config.get("credentials_path", "gmail_credentials.json")

        # Check for environment variable-based authentication
        client_id = os.getenv("GMAIL_CLIENT_ID")
        client_secret = os.getenv("GMAIL_CLIENT_SECRET")
        redirect_uri = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:0")

        # Load existing credentials from token
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Try environment variables first, then fall back to credentials file
                if client_id and client_secret:
                    # Use environment variables to create OAuth flow
                    client_config = {
                        "installed": {
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "redirect_uris": [redirect_uri, "http://localhost"],
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                    flow = InstalledAppFlow.from_client_config(
                        client_config, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                elif os.path.exists(credentials_path):
                    # Fall back to credentials file
                    flow = InstalledAppFlow.from_client_secrets_file(
                        credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                else:
                    raise RuntimeError(
                        f"Gmail credentials not found. Either: \n"
                        f"1. Set environment variables: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET\n"
                        f"2. Or provide credentials file at {credentials_path}\n"
                        "See GMAIL_SETUP.md for setup instructions."
                    )

            # Save the credentials for the next run
            with open(token_path, "w") as token:
                token.write(creds.to_json())

        self.credentials = creds
        self.service = build("gmail", "v1", credentials=creds)
        self._initialized = True

    def get_tools(self) -> list[dict[str, Any]]:
        """Get Gmail tools."""
        return [
            {
                "name": "gmail_list_messages",
                "description": "List Gmail messages with optional query filters. Returns message IDs and snippets.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Gmail search query (e.g., 'is:unread', 'from:example@gmail.com', 'subject:meeting')",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return (default: 10)",
                            "default": 10,
                        },
                    },
                },
            },
            {
                "name": "gmail_get_message",
                "description": "Get full details of a Gmail message by ID, including subject, sender, body, and attachments.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "The Gmail message ID",
                        },
                    },
                    "required": ["message_id"],
                },
            },
            {
                "name": "gmail_send_message",
                "description": "Send an email via Gmail.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient email address",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject",
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body (plain text)",
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC email addresses (comma-separated)",
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC email addresses (comma-separated)",
                        },
                    },
                    "required": ["to", "subject", "body"],
                },
            },
            {
                "name": "gmail_search",
                "description": "Search Gmail with advanced queries and get detailed results.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Gmail search query (supports all Gmail search operators)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 20)",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "gmail_mark_as_read",
                "description": "Mark a Gmail message as read.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "The Gmail message ID",
                        },
                    },
                    "required": ["message_id"],
                },
            },
            {
                "name": "gmail_mark_as_unread",
                "description": "Mark a Gmail message as unread.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "The Gmail message ID",
                        },
                    },
                    "required": ["message_id"],
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a Gmail tool."""
        if not self.service:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Gmail service not initialized. Please check authentication.",
                    }
                ],
                "isError": True,
            }

        try:
            if name == "gmail_list_messages":
                return await self._list_messages(
                    query=arguments.get("query", ""),
                    max_results=arguments.get("max_results", 10),
                )
            elif name == "gmail_get_message":
                return await self._get_message(arguments["message_id"])
            elif name == "gmail_send_message":
                return await self._send_message(
                    to=arguments["to"],
                    subject=arguments["subject"],
                    body=arguments["body"],
                    cc=arguments.get("cc"),
                    bcc=arguments.get("bcc"),
                )
            elif name == "gmail_search":
                return await self._search_messages(
                    query=arguments["query"],
                    max_results=arguments.get("max_results", 20),
                )
            elif name == "gmail_mark_as_read":
                return await self._mark_as_read(arguments["message_id"])
            elif name == "gmail_mark_as_unread":
                return await self._mark_as_unread(arguments["message_id"])
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True,
                }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    async def _list_messages(
        self, query: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        """List Gmail messages."""
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])

        if not messages:
            return {
                "content": [{"type": "text", "text": "No messages found."}],
            }

        # Get snippets for each message
        message_list = []
        for msg in messages:
            msg_data = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata")
                .execute()
            )
            headers = msg_data.get("payload", {}).get("headers", [])
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            from_email = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown",
            )

            message_list.append(
                {
                    "id": msg["id"],
                    "subject": subject,
                    "from": from_email,
                    "snippet": msg_data.get("snippet", ""),
                }
            )

        output = f"Found {len(message_list)} message(s):\n\n"
        for i, msg in enumerate(message_list, 1):
            output += f"{i}. ID: {msg['id']}\n"
            output += f"   From: {msg['from']}\n"
            output += f"   Subject: {msg['subject']}\n"
            output += f"   Snippet: {msg['snippet']}\n\n"

        return {
            "content": [{"type": "text", "text": output}],
        }

    async def _get_message(self, message_id: str) -> dict[str, Any]:
        """Get full message details."""
        msg = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        headers = msg.get("payload", {}).get("headers", [])
        subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"),
            "No Subject",
        )
        from_email = next(
            (h["value"] for h in headers if h["name"].lower() == "from"), "Unknown"
        )
        to_email = next(
            (h["value"] for h in headers if h["name"].lower() == "to"), "Unknown"
        )
        date = next(
            (h["value"] for h in headers if h["name"].lower() == "date"), "Unknown"
        )

        # Extract body
        body = self._extract_body(msg.get("payload", {}))

        output = f"Message ID: {message_id}\n"
        output += f"From: {from_email}\n"
        output += f"To: {to_email}\n"
        output += f"Subject: {subject}\n"
        output += f"Date: {date}\n"
        output += f"\n{body}"

        return {
            "content": [{"type": "text", "text": output}],
        }

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract message body from payload."""
        if "parts" in payload:
            parts = payload["parts"]
            for part in parts:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8")
            # If no plain text, try HTML
            for part in parts:
                if part["mimeType"] == "text/html":
                    data = part["body"].get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8")
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8")
        return ""

    async def _send_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict[str, Any]:
        """Send an email."""
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_message = {"raw": raw}

        result = (
            self.service.users()
            .messages()
            .send(userId="me", body=send_message)
            .execute()
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Message sent successfully. Message ID: {result['id']}",
                }
            ],
        }

    async def _search_messages(
        self, query: str, max_results: int = 20
    ) -> dict[str, Any]:
        """Search messages with detailed results."""
        return await self._list_messages(query=query, max_results=max_results)

    async def _mark_as_read(self, message_id: str) -> dict[str, Any]:
        """Mark message as read."""
        self.service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

        return {
            "content": [
                {"type": "text", "text": f"Message {message_id} marked as read."}
            ],
        }

    async def _mark_as_unread(self, message_id: str) -> dict[str, Any]:
        """Mark message as unread."""
        self.service.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": ["UNREAD"]}
        ).execute()

        return {
            "content": [
                {"type": "text", "text": f"Message {message_id} marked as unread."}
            ],
        }
