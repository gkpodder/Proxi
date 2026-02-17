"""Gmail API tools for MCP server."""

import base64
import json
import os
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

# Load .env file
load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailTools:
    """Tools for interacting with Gmail API."""

    def __init__(self):
        """Initialize Gmail tools with credentials."""
        self.service = None
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate with Gmail API using OAuth 2.0."""
        token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")
        client_id = os.getenv("GMAIL_CLIENT_ID")
        client_secret = os.getenv("GMAIL_CLIENT_SECRET")
        redirect_uri = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8765")

        creds = None

        # Load existing token if available
        if Path(token_path).exists():
            try:
                with open(token_path, "r") as token_file:
                    token_data = json.load(token_file)
                    creds = Credentials.from_authorized_user_info(token_data)
            except Exception as e:
                logger.warning("gmail_token_load_error", error=str(e))

        # If no valid credentials, create new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Create credentials from environment variables
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://accounts.google.com/o/oauth2/token",
                        "redirect_uris": [redirect_uri],
                    }
                }

                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                creds = flow.run_local_server(port=8765)

            # Save credentials for future use
            if creds:
                token_data = json.loads(creds.to_json())
                with open(token_path, "w") as token_file:
                    json.dump(token_data, token_file)

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("gmail_authenticated")

    async def read_emails(self, max_results: int = 10, query: str = "") -> dict[str, Any]:
        """Read emails from Gmail inbox."""
        try:
            if not self.service:
                return {"error": "Gmail service not initialized"}

            search_query = query if query else "is:inbox"

            # Get message IDs
            results = self.service.users().messages().list(
                userId="me",
                q=search_query,
                maxResults=max_results
            ).execute()

            messages = results.get("messages", [])
            emails = []

            for msg in messages:
                msg_id = msg["id"]
                message = self.service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="full"
                ).execute()

                headers = message["payload"]["headers"]
                email_data = {
                    "id": msg_id,
                    "from": next(
                        (h["value"] for h in headers if h["name"] == "From"),
                        "Unknown"
                    ),
                    "to": next(
                        (h["value"] for h in headers if h["name"] == "To"),
                        "Unknown"
                    ),
                    "subject": next(
                        (h["value"] for h in headers if h["name"] == "Subject"),
                        "(No Subject)"
                    ),
                    "date": next(
                        (h["value"] for h in headers if h["name"] == "Date"),
                        ""
                    ),
                }

                # Try to get body
                try:
                    if "parts" in message["payload"]:
                        for part in message["payload"]["parts"]:
                            if part["mimeType"] == "text/plain":
                                if "data" in part["body"]:
                                    email_data["body"] = base64.urlsafe_b64decode(
                                        part["body"]["data"]
                                    ).decode("utf-8")
                                break
                    elif "body" in message["payload"] and "data" in message["payload"]["body"]:
                        email_data["body"] = base64.urlsafe_b64decode(
                            message["payload"]["body"]["data"]
                        ).decode("utf-8")
                except Exception as e:
                    logger.warning("gmail_body_parse_error", error=str(e))
                    email_data["body"] = "(Unable to parse body)"

                emails.append(email_data)

            return {"emails": emails, "count": len(emails)}

        except HttpError as e:
            logger.error("gmail_read_error", error=str(e))
            return {"error": f"Gmail API error: {str(e)}"}

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None
    ) -> dict[str, Any]:
        """Send an email via Gmail."""
        try:
            if not self.service:
                return {"error": "Gmail service not initialized"}

            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject

            if cc:
                message["cc"] = cc
            if bcc:
                message["bcc"] = bcc

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

            send_message = {
                "raw": raw_message
            }

            result = self.service.users().messages().send(
                userId="me",
                body=send_message
            ).execute()

            logger.info("gmail_sent", to=to, subject=subject)
            return {
                "status": "sent",
                "messageId": result["id"],
                "to": to,
                "subject": subject
            }

        except HttpError as e:
            logger.error("gmail_send_error", error=str(e))
            return {"error": f"Gmail API error: {str(e)}"}

    async def get_email(self, email_id: str) -> dict[str, Any]:
        """Get details of a specific email."""
        try:
            if not self.service:
                return {"error": "Gmail service not initialized"}

            message = self.service.users().messages().get(
                userId="me",
                id=email_id,
                format="full"
            ).execute()

            headers = message["payload"]["headers"]
            email_data = {
                "id": email_id,
                "from": next(
                    (h["value"] for h in headers if h["name"] == "From"),
                    "Unknown"
                ),
                "to": next(
                    (h["value"] for h in headers if h["name"] == "To"),
                    "Unknown"
                ),
                "subject": next(
                    (h["value"] for h in headers if h["name"] == "Subject"),
                    "(No Subject)"
                ),
                "date": next(
                    (h["value"] for h in headers if h["name"] == "Date"),
                    ""
                ),
                "labels": message.get("labelIds", []),
            }

            # Get body
            try:
                if "parts" in message["payload"]:
                    for part in message["payload"]["parts"]:
                        if part["mimeType"] == "text/plain":
                            if "data" in part["body"]:
                                email_data["body"] = base64.urlsafe_b64decode(
                                    part["body"]["data"]
                                ).decode("utf-8")
                            break
                elif "body" in message["payload"] and "data" in message["payload"]["body"]:
                    email_data["body"] = base64.urlsafe_b64decode(
                        message["payload"]["body"]["data"]
                    ).decode("utf-8")
            except Exception as e:
                logger.warning("gmail_body_parse_error", error=str(e))
                email_data["body"] = "(Unable to parse body)"

            return email_data

        except HttpError as e:
            logger.error("gmail_get_error", error=str(e))
            return {"error": f"Gmail API error: {str(e)}"}
