import json
import os
import sys
from typing import Any, Dict

from dotenv import load_dotenv
from openai import OpenAI

from server import gmail_get_message, gmail_search, gmail_send, gmail_summarize

load_dotenv()


def _get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def plan_action(prompt: str) -> Dict[str, Any]:
    client = OpenAI(api_key=_get_env("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    schema = {
        "name": "gmail_action",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "get", "send", "summarize"],
                },
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
                "message_id": {"type": "string"},
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["action"],
        },
    }

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You map a natural language request to a Gmail action."
                " Use query for search/summarize, message_id for get, and to/subject/body for send.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_schema", "json_schema": schema},
    )

    return json.loads(resp.choices[0].message.content)


def execute_action(plan: Dict[str, Any]) -> Dict[str, Any]:
    action = plan["action"]
    if action == "search":
        return {
            "result": gmail_search(plan.get("query", ""), plan.get("max_results", 10))
        }
    if action == "get":
        return {"result": gmail_get_message(plan.get("message_id", ""))}
    if action == "send":
        return {
            "result": gmail_send(
                plan.get("to", ""),
                plan.get("subject", ""),
                plan.get("body", ""),
            )
        }
    if action == "summarize":
        return {
            "result": gmail_summarize(plan.get("query", ""), plan.get("max_results", 5))
        }

    raise RuntimeError(f"Unknown action: {action}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python cli.py \"your request\"")
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    plan = plan_action(prompt)
    result = execute_action(plan)
    print(json.dumps({"plan": plan, **result}, indent=2))


if __name__ == "__main__":
    main()
