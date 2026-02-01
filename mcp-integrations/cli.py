import json
import os
import re
import sys
from typing import Any, Dict

from dotenv import load_dotenv
from openai import OpenAI

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.logger import setup_logger

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
logger = setup_logger("MCPIntegrations", log_dir=LOG_DIR)

# Import tools from both servers
try:
    from gmail_server import gmail_get_message, gmail_search, gmail_send, gmail_summarize
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False

try:
    from notion_server import (
        notion_search_pages,
        notion_get_page,
        notion_create_page,
        notion_update_page,
        notion_list_databases,
    )
    NOTION_AVAILABLE = True
except ImportError:
    NOTION_AVAILABLE = False

load_dotenv()


def _get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def plan_action(prompt: str) -> Dict[str, Any]:
    logger.info("Planning action from prompt")
    client = OpenAI(api_key=_get_env("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Build schema based on available services
    action_enum = []
    if GMAIL_AVAILABLE:
        action_enum.extend(["gmail_search", "gmail_get", "gmail_send", "gmail_summarize"])
    if NOTION_AVAILABLE:
        action_enum.extend(["notion_search", "notion_get", "notion_create", "notion_update", "notion_list_dbs"])

    schema = {
        "name": "action_plan",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": action_enum,
                },
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
                "message_id": {"type": "string"},
                "page_id": {"type": "string"},
                "database_id": {"type": "string"},
                "parent_page_id": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["action"],
        },
    }

    system_prompt = "You map a natural language request to an action."
    if GMAIL_AVAILABLE:
        system_prompt += " Gmail: query/message_id for search/get, to/subject/body for send, query for summarize."
    if NOTION_AVAILABLE:
        system_prompt += (
            " Notion: query for search, page_id for get, database_id/title/content or parent_page_id/title/content for create, "
            "page_id/content for update (if no page_id, provide query or title to find the page)."
        )

    logger.info("Sending prompt to OpenAI model=%s", model)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_schema", "json_schema": schema},
    )
    logger.info("Received response from OpenAI")
    plan = json.loads(resp.choices[0].message.content)
    logger.info("Planned action: %s", plan)
    return plan


def execute_action(plan: Dict[str, Any]) -> Dict[str, Any]:
    if "action" not in plan:
        logger.error("Plan missing action: %s", plan)
        raise RuntimeError(f"Invalid plan returned from model: {plan}")
    action = plan["action"]
    logger.info("Executing action: %s", action)
    
    # Gmail actions
    if action == "gmail_search" and GMAIL_AVAILABLE:
        logger.info("Calling gmail_search")
        return {"result": gmail_search(plan.get("query", ""), plan.get("max_results", 10))}
    if action == "gmail_get" and GMAIL_AVAILABLE:
        logger.info("Calling gmail_get_message")
        return {"result": gmail_get_message(plan.get("message_id", ""))}
    if action == "gmail_send" and GMAIL_AVAILABLE:
        logger.info("Calling gmail_send")
        return {"result": gmail_send(plan.get("to", ""), plan.get("subject", ""), plan.get("body", ""))}
    if action == "gmail_summarize" and GMAIL_AVAILABLE:
        logger.info("Calling gmail_summarize")
        return {"result": gmail_summarize(plan.get("query", ""), plan.get("max_results", 5))}
    
    # Notion actions
    if action == "notion_search" and NOTION_AVAILABLE:
        logger.info("Calling notion_search_pages")
        return {"result": notion_search_pages(plan.get("query", ""), plan.get("max_results", 10))}
    if action == "notion_get" and NOTION_AVAILABLE:
        logger.info("Calling notion_get_page")
        return {"result": notion_get_page(plan.get("page_id", ""))}
    if action == "notion_create" and NOTION_AVAILABLE:
        logger.info("Calling notion_create_page")
        return {
            "result": notion_create_page(
                plan.get("database_id", ""),
                plan.get("title", ""),
                plan.get("content", ""),
                plan.get("parent_page_id", ""),
            )
        }
    if action == "notion_update" and NOTION_AVAILABLE:
        logger.info("Calling notion_update_page")
        page_id = plan.get("page_id", "")
        if page_id and not re.fullmatch(r"[0-9a-fA-F-]{32,36}", page_id):
            page_id = ""
        if not page_id:
            search_query = plan.get("query", "") or plan.get("title", "")
            if search_query:
                # Extract a page id from a URL or slug+id string if present
                if "notion.so" in search_query:
                    page_id = search_query.split("/")[-1].split("?")[0]
                if not page_id:
                    # try to pull 32+ hex from the query
                    m = re.search(r"[0-9a-fA-F]{32,}", search_query)
                    if m:
                        page_id = m.group(0)
                if not page_id:
                    matches = notion_search_pages(search_query, 1)
                    if matches:
                        page_id = matches[0].get("id", "")
        if not page_id:
            raise RuntimeError("Missing page_id. Provide page_id or a query/title to locate the page.")
        return {"result": notion_update_page(page_id, plan.get("content", ""))}
    if action == "notion_list_dbs" and NOTION_AVAILABLE:
        logger.info("Calling notion_list_databases")
        return {"result": notion_list_databases()}

    raise RuntimeError(f"Unknown action or service unavailable: {action}")


def main() -> None:
    if len(sys.argv) < 2:
        logger.info("Usage: python cli.py \"your request\"")
        logger.info("Available services: Gmail=%s, Notion=%s", GMAIL_AVAILABLE, NOTION_AVAILABLE)
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    logger.info("Received CLI prompt")
    plan = plan_action(prompt)
    result = execute_action(plan)
    logger.info(json.dumps({"plan": plan, **result}, indent=2))


if __name__ == "__main__":
    main()
