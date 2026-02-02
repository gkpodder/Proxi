# Browser Sub-Agent Integration - Quick Start

## What's New

The browser-subagent is now integrated into Proxi as a sub-agent! The main agent can now delegate web browsing tasks automatically.

## Setup

### 1. Install Dependencies

```bash
# Create/activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install proxi with browser dependencies
pip install -e .

# Install Playwright browsers (required for browser agent)
playwright install chromium
```

### 2. Set API Key

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

## Quick Test

### Test Integration (No Browser Execution)

```bash
python test_integration_quick.py
```

Expected output:
```
✅ ALL INTEGRATION TESTS PASSED!
Registered sub-agents:
  - summarizer: ...
  - browser: ...
```

### Test Browser Execution

```bash
python test_browser_integration.py
```

This will:
1. Launch headless Chrome
2. Navigate to example.com
3. Extract page title
4. Return results

### View Examples

```bash
python examples_browser_usage.py
```

## Usage

### Direct Usage (Proxi CLI)

```bash
# Simple navigation
proxi "Visit example.com and tell me what you see"

# Search task
proxi "Search Google for Python tutorials and list the top 3 results"

# Complex task
proxi "Go to Wikipedia, search for 'Artificial Intelligence', and summarize the intro paragraph"
```

The main agent will automatically:
- Recognize the task requires web browsing
- Select the browser sub-agent
- Execute the browser automation
- Return results

### Programmatic Usage

```python
from proxi.agents.browser import BrowserAgent
from proxi.agents.base import AgentContext

# Create browser agent
browser = BrowserAgent(headless=True, max_steps=20)

# Create context
context = AgentContext(
    task="Navigate to example.com and extract the title",
    context_refs={"start_url": "https://example.com"},
    history_snapshot=[],
)

# Run browser task
result = await browser.run(context, max_turns=10, max_time=30.0)

print(f"Success: {result.success}")
print(f"Result: {result.artifacts.get('result_data')}")
```

## Configuration

Edit `proxi/cli/main.py` to configure browser agent:

```python
browser_agent = BrowserAgent(
    headless=True,                    # Run in headless mode
    max_steps=20,                     # Max browser steps
    allowed_domains=[],               # Empty = allow all
    denied_domains=["malicious.com"], # Block specific domains
    artifacts_base_dir="./browser_artifacts",  # Screenshot storage
)
```

## Architecture

```
User Request
     ↓
Proxi Main Agent (Planner)
     ↓
  (decides: use browser sub-agent)
     ↓
Browser Sub-Agent Adapter (proxi/agents/browser.py)
     ↓
Browser Agent Core (browser-subagent/app/)
     ↓
Playwright (Chrome automation)
     ↓
Results back to Main Agent
     ↓
Response to User
```

## What's Integrated

✅ **Browser Agent Adapter** - `proxi/agents/browser.py`
- Maps Proxi models ↔ Browser agent models
- Handles browser lifecycle
- Manages artifacts and results

✅ **Automatic Registration** - `proxi/cli/main.py`
- Browser agent auto-registered with other sub-agents
- Available to planner for task delegation

✅ **Dependencies** - `pyproject.toml`
- Playwright for browser automation
- httpx for HTTP requests

✅ **Tests & Examples**
- Integration tests (no browser needed)
- Full execution tests (with browser)
- Usage examples

## Troubleshooting

### "playwright not found"
```bash
playwright install chromium
```

### "OPENAI_API_KEY not set"
```bash
export OPENAI_API_KEY="your-key"
```

### Import errors
```bash
# Reinstall proxi
pip install -e .
```

### Browser hangs
- Check max_steps isn't too high
- Reduce max_time constraint
- Check allowed_domains configuration

## Files

### New Files
- `proxi/agents/browser.py` - Browser agent adapter
- `test_integration_quick.py` - Integration tests
- `test_browser_integration.py` - Execution tests
- `examples_browser_usage.py` - Usage examples
- `BROWSER_INTEGRATION.md` - Detailed docs
- `BROWSER_INTEGRATION_QUICKSTART.md` - This file

### Modified Files
- `pyproject.toml` - Added playwright, httpx
- `proxi/cli/main.py` - Registered browser agent
- `.gitignore` - Added browser_artifacts/

## More Info

See `BROWSER_INTEGRATION.md` for detailed technical documentation.
