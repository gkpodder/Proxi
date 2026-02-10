"""Gmail MCP integration using MCP protocol."""

import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from proxi.observability.logging import get_logger

logger = get_logger(__name__)

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _get_env(name: str, default: Optional[str] = None) -> str:
    """Get environment variable with optional default."""
    value = os.getenv(name, default)
    if not value and default is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return value or default or ""


def get_gmail_service() -> Any:
    """Initialize and return Gmail API service."""
    logger.debug("mcp_gmail_init_service", action="initialize")
    token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")

    creds = None
    if os.path.exists(token_path):
        logger.debug("mcp_gmail_load_token", path=token_path)
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("mcp_gmail_refresh_token", action="refresh")
            creds.refresh(Request())
        else:
            logger.info("mcp_gmail_oauth_flow", action="start")
            client_id = _get_env("GMAIL_CLIENT_ID")
            client_secret = _get_env("GMAIL_CLIENT_SECRET")
            redirect_uri = _get_env("GMAIL_REDIRECT_URI", "http://localhost:8765")

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
        logger.info("mcp_gmail_token_saved", path=token_path)

    logger.debug("mcp_gmail_service_ready", status="connected")
    return build("gmail", "v1", credentials=creds)


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
                "name": "gmail",
                "version": "1.0.0"
            }
        }
    })


def _handle_list_tools(request_id: int) -> None:
    """Handle MCP list_tools request."""
    tools = [
        {
            "name": "gmail_search",
            "description": "Search Gmail and return message metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query"
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
            "name": "gmail_get_message",
            "description": "Get a Gmail message body.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The message ID to retrieve"
                    }
                },
                "required": ["message_id"]
            }
        },
        {
            "name": "gmail_send",
            "description": "Send a Gmail message.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Message subject"
                    },
                    "body": {
                        "type": "string",
                        "description": "Message body"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        },
        {
            "name": "gmail_summarize",
            "description": "Search Gmail and summarize with OpenAI.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum emails to summarize",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "gmail_get_labels",
            "description": "Get all Gmail labels.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "gmail_move_to_trash",
            "description": "Move a Gmail message to trash.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The message ID to move to trash"
                    }
                },
                "required": ["message_id"]
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
        if tool_name == "gmail_search":
            result = _tool_gmail_search(arguments)
        elif tool_name == "gmail_get_message":
            result = _tool_gmail_get_message(arguments)
        elif tool_name == "gmail_send":
            result = _tool_gmail_send(arguments)
        elif tool_name == "gmail_summarize":
            result = _tool_gmail_summarize(arguments)
        elif tool_name == "gmail_get_labels":
            result = _tool_gmail_get_labels(arguments)
        elif tool_name == "gmail_move_to_trash":
            result = _tool_gmail_move_to_trash(arguments)
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
        logger.error("tool_error", tool=tool_name, error=str(e))
        _send_error(request_id, -32603, f"Tool error: {str(e)}")


def _tool_gmail_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search Gmail."""
    query = args.get("query", "")
    max_results = args.get("max_results", 10)
    
    logger.info("mcp_gmail_search", query=query, max_results=max_results)
    service = get_gmail_service()
    
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = resp.get("messages", [])
    
    results = []
    for msg in messages:
        logger.debug("mcp_gmail_get_metadata", msg_id=msg.get("id"))
        msg_data = service.users().messages().get(
            userId="me", 
            id=msg["id"], 
            format="metadata"
        ).execute()
        
        headers = msg_data.get("payload", {}).get("headers", [])
        header_map = {h["name"].lower(): h["value"] for h in headers}
        
        results.append({
            "id": msg_data.get("id"),
            "threadId": msg_data.get("threadId"),
            "subject": header_map.get("subject"),
            "from": header_map.get("from"),
            "to": header_map.get("to"),
            "date": header_map.get("date"),
            "snippet": msg_data.get("snippet"),
        })
    
    logger.info("mcp_gmail_search_complete", count=len(results))
    return {"messages": results}


def _tool_gmail_get_message(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get message content."""
    message_id = args.get("message_id", "")
    
    logger.info("mcp_gmail_get_message", msg_id=message_id)
    service = get_gmail_service()
    
    msg_data = service.users().messages().get(
        userId="me", 
        id=message_id, 
        format="full"
    ).execute()

    def _extract_text(payload: Dict[str, Any]) -> str:
        """Extract text from MIME payload recursively."""
        body = payload.get("body", {}).get("data")
        if body:
            return base64.urlsafe_b64decode(body.encode("utf-8")).decode(
                "utf-8", errors="replace"
            )
        
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data.encode("utf-8")).decode(
                        "utf-8", errors="replace"
                    )
        
        for part in parts:
            nested = _extract_text(part)
            if nested:
                return nested
        
        return ""

    body = _extract_text(msg_data.get("payload", {}))
    
    logger.debug("mcp_gmail_get_message_complete", msg_id=message_id)
    return {
        "id": msg_data.get("id"),
        "threadId": msg_data.get("threadId"),
        "snippet": msg_data.get("snippet"),
        "body": body,
    }


def _tool_gmail_send(args: Dict[str, Any]) -> Dict[str, Any]:
    """Send an email."""
    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    
    logger.info("mcp_gmail_send", to=to, subject=subject)
    service = get_gmail_service()
    
    raw = f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}"
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
    
    msg = service.users().messages().send(userId="me", body={"raw": encoded}).execute()
    
    logger.info("mcp_gmail_send_complete", msg_id=msg.get("id"))
    return {"id": msg.get("id"), "threadId": msg.get("threadId")}


def _tool_gmail_summarize(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search and summarize emails."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("mcp_gmail_summarize_missing_openai")
        raise RuntimeError("OpenAI library not installed")
    
    query = args.get("query", "")
    max_results = args.get("max_results", 5)
    
    logger.info("mcp_gmail_summarize", query=query, max_results=max_results)
    
    client = OpenAI(api_key=_get_env("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    messages = _tool_gmail_search({"query": query, "max_results": max_results})["messages"]
    bodies = []
    
    for m in messages:
        full = _tool_gmail_get_message({"message_id": m["id"]})
        bodies.append({
            "id": m["id"],
            "subject": m.get("subject"),
            "body": full.get("body", ""),
        })

    prompt = "Summarize these emails:\n" + "\n---\n".join(
        f"Subject: {e['subject']}\n{e['body']}" for e in bodies
    )

    logger.debug("mcp_gmail_summarize_request", model=model)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    
    logger.info("mcp_gmail_summarize_complete")
    return {"summary": resp.choices[0].message.content}


def _tool_gmail_get_labels(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get all labels."""
    logger.info("mcp_gmail_get_labels")
    service = get_gmail_service()
    
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])
    
    logger.info("mcp_gmail_get_labels_complete", count=len(labels))
    return {"labels": labels}


def _tool_gmail_move_to_trash(args: Dict[str, Any]) -> Dict[str, Any]:
    """Move message to trash."""
    message_id = args.get("message_id", "")
    
    logger.info("mcp_gmail_move_to_trash", msg_id=message_id)
    service = get_gmail_service()
    
    service.users().messages().trash(userId="me", id=message_id).execute()
    logger.info("mcp_gmail_move_to_trash_complete", msg_id=message_id)
    return {"status": "success", "id": message_id, "action": "moved to trash"}


def main():
    """Main MCP server loop."""
    logger.info("mcp_gmail_server_start")
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            
            logger.debug("mcp_request", method=method, id=request_id)
            
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
            logger.debug("json_decode_error")
            continue
        except Exception as e:
            logger.error("mcp_error", error=str(e), exc_info=True)
            continue


if __name__ == "__main__":
    main()

