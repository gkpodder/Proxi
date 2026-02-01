# MCP Gmail + OpenAI (Python)

## Setup
**Requires Python 3.10+**
1) Create a Google Cloud OAuth client (Desktop app) and enable Gmail API.
2) Copy `.env.example` to `.env` and fill values.
3) Install deps:


```bash
pip install -r requirements.txt
```

## Run
```bash
python server.py
```

## CLI (natural language)
```bash
python cli.py "summarize my unread emails from last week"
```

## First Run
It will create a `token.json` file after authorizing from browser. THis is used
in future runs.

## MCP Tools
- `gmail_search(query, max_results=10)`
- `gmail_get_message(message_id)`
- `gmail_send(to, subject, body)`
- `gmail_summarize(query, max_results=5)`
