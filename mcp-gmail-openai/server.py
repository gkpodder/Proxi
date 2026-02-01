import os
import json
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from openai import OpenAI

from mcp.server.fastmcp import FastMCP

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_gmail_service() -> Any:
    token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_id = _get_env("GMAIL_CLIENT_ID")
            client_secret = _get_env("GMAIL_CLIENT_SECRET")
            redirect_uri = _get_env("GMAIL_REDIRECT_URI")

            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uris": [redirect_uri],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                },
                SCOPES,
            )
            creds = flow.run_local_server(
                host="localhost",
                port=int(redirect_uri.split(":")[-1]),
                prompt="consent",
                authorization_prompt_message="Please authorize access to Gmail.",
            )

        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


client = OpenAI(api_key=_get_env("OPENAI_API_KEY"))
model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

mcp = FastMCP("gmail-openai")


@mcp.tool()
def gmail_search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Search Gmail and return message metadata."""
    service = get_gmail_service()
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = resp.get("messages", [])
    results = []
    for msg in messages:
        msg_data = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
        headers = msg_data.get("payload", {}).get("headers", [])
        header_map = {h["name"].lower(): h["value"] for h in headers}
        results.append(
            {
                "id": msg_data.get("id"),
                "threadId": msg_data.get("threadId"),
                "subject": header_map.get("subject"),
                "from": header_map.get("from"),
                "to": header_map.get("to"),
                "date": header_map.get("date"),
                "snippet": msg_data.get("snippet"),
            }
        )
    return results


@mcp.tool()
def gmail_get_message(message_id: str) -> Dict[str, Any]:
    """Get a Gmail message body (plain text if available)."""
    service = get_gmail_service()
    msg_data = service.users().messages().get(userId="me", id=message_id, format="full").execute()

    def _extract_text(payload: Dict[str, Any]) -> str:
        import base64

        body = payload.get("body", {}).get("data")
        if body:
            return base64.urlsafe_b64decode(body.encode("utf-8")).decode("utf-8", errors="replace")
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
        for part in parts:
            nested = _extract_text(part)
            if nested:
                return nested
        return ""

    body = _extract_text(msg_data.get("payload", {}))
    return {
        "id": msg_data.get("id"),
        "threadId": msg_data.get("threadId"),
        "snippet": msg_data.get("snippet"),
        "body": body,
    }


@mcp.tool()
def gmail_send(to: str, subject: str, body: str) -> Dict[str, Any]:
    """Send a Gmail message."""
    import base64

    service = get_gmail_service()
    raw = f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}"
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
    msg = service.users().messages().send(userId="me", body={"raw": encoded}).execute()
    return {"id": msg.get("id"), "threadId": msg.get("threadId")}


@mcp.tool()
def gmail_summarize(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search Gmail, fetch messages, and summarize with OpenAI."""
    messages = gmail_search(query, max_results=max_results)
    bodies = []
    for m in messages:
        full = gmail_get_message(m["id"])
        bodies.append({"id": m["id"], "subject": m.get("subject"), "body": full.get("body", "")})

    prompt = {
        "instructions": "Summarize the key points across these emails.",
        "emails": bodies,
    }

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": json.dumps(prompt),
            }
        ],
    )

    return {"summary": resp.choices[0].message.content}


if __name__ == "__main__":
    mcp.run()
