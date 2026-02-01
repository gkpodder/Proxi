# MCP Gmail + OpenAI (Python)

## Setup
**Requires Python 3.10+**
2) Create a Notion integration and get API key: https://www.notion.so/my-integrations
3) Copy `.env.example` to `.env` and fill values.
4) Install deps:
3) Install deps:


```bash
pip install -r requirements.txt
```
### MCP Server Mode

python gmail_server.py  # Gmail MCP
python notion_server.py  # Notion MCP
```bash
python server.py
### CLI Mode (natural language - works with Gmail or Notion)

## CLI (natural language)
python cli.py "search my Notion for notes about Python"
python cli.py "create a new Notion page with my meeting notes"
```bash
python cli.py "summarize my unread emails from last week"
## Available Tools

### Gmail
- `gmail_search(query, max_results=10)` - Search emails
- `gmail_get_message(message_id)` - Get email body
- `gmail_send(to, subject, body)` - Send email
- `gmail_summarize(query, max_results=5)` - Summarize emails with OpenAI

### Notion
- `notion_search_pages(query, max_results=10)` - Search pages
- `notion_get_page(page_id)` - Get page content
- `notion_create_page(database_id, title, content)` - Create page
- `notion_update_page(page_id, content)` - Update page
- `notion_list_databases()` - List all databases

## MCP Tools
- `gmail_search(query, max_results=10)`
- `gmail_get_message(message_id)`
- `gmail_send(to, subject, body)`
- `gmail_summarize(query, max_results=5)`
