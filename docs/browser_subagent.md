# Browser Sub-Agent Implementation Guide

## Overview

The **browser sub-agent** (`BrowserSubAgent`) is a fresh, tool-driven worker implementation integrated into Proxi's multi-agent architecture. It delegates web-focused tasks (research, scraping, forms, monitoring, shopping/travel discovery) to a dedicated loop that uses registered web-capable tools.

## Key Design Principles

1. **Tool-driven execution**: BrowserSubAgent does not directly control a browser. Instead, it selects and calls web-capable tools registered in the system's `ToolRegistry`.

2. **Isolated worker loop**: Runs its own decision loop (max_turns, max_tokens, max_time budgets) to avoid context bloat in the main orchestrator.

3. **Progress streaming**: Emits structured events at each loop iteration so the TUI/bridge can display real-time status updates.

4. **Safe and bounded**: Enforces turn/token/time limits. Returns partial results if limits are reached before explicit completion.

## Integration Points

### 1. Registration ([proxi/cli/main.py](../proxi/cli/main.py))

The browser agent is registered in `setup_sub_agents()` alongside the summarizer agent:

```python
from proxi.agents.browser import BrowserSubAgent

def setup_sub_agents(
    llm_client: OpenAIClient | AnthropicClient,
    tool_registry: ToolRegistry,
) -> SubAgentManager:
    registry = SubAgentRegistry()
    
    # Register summarizer agent
    summarizer = SummarizerAgent(llm_client)
    registry.register(summarizer)
    
    # Register browser agent
    browser_agent = BrowserSubAgent(llm_client=llm_client, tool_registry=tool_registry)
    registry.register(browser_agent)
    
    manager = SubAgentManager(registry)
    return manager
```

### 2. Orchestrator Routing ([proxi/core/loop.py](../proxi/core/loop.py))

When the main orchestrator decides on a `SUB_AGENT_CALL` decision targeting the `browser` agent, the browser worker is invoked via `SubAgentManager.run()`.

The orchestrator builds an `AgentContext` and optionally injects a `__progress_hook__` callback for loop events:

```python
if self.emitter:
    def progress_hook(payload: dict[str, Any]) -> None:
        self.emitter.emit({
            "type": "subagent_progress",
            "agent": agent_name,
            "payload": payload,
        })
    
    context_refs["__progress_hook__"] = progress_hook
```

### 3. Tool Selection ([proxi/agents/browser.py](../proxi/agents/browser.py))

BrowserSubAgent filters the full `ToolRegistry` by keyword matching to identify web-capable tools:

```python
def _select_web_tools(self) -> list[ToolSpec]:
    """Select likely web/browser-capable tools from the registry."""
    tool_specs = self.tool_registry.to_specs()
    web_keywords = {
        "web", "browser", "url", "http", "scrape", "search", "page",
        "site", "form", "monitor", "travel", "shopping", "fetch", "navigate",
    }
    
    selected: list[ToolSpec] = []
    for spec in tool_specs:
        haystack = f"{spec.name} {spec.description}".lower()
        if any(k in haystack for k in web_keywords):
            selected.append(spec)
    
    return selected
```

If no web tools are found, the agent fails fast with a clear error.

### 4. Loop Execution

BrowserSubAgent runs a turn-by-turn loop:

1. **DECIDE**: Call LLM with web tool specs to decide next action.
2. **ACT**: Execute tool via `ToolRegistry.execute()`.
3. **OBSERVE**: Capture tool result (success/error/output).
4. **EMIT PROGRESS**: Send structured event via progress hook (if present).
5. **REPEAT** until:
   - LLM returns `RESPOND` decision (task complete)
   - Turn/token/time limit reached
   - Error condition

### 5. Progress Events

BrowserSubAgent emits the following event types:

| Event Type | Description |
|------------|-------------|
| `browser_loop_start` | Worker loop started; includes session_id and task. |
| `browser_loop_turn` | Turn N started; deciding next action. |
| `browser_tool_start` | Tool execution started; includes tool name and arguments. |
| `browser_tool_done` | Tool execution finished; includes success/error. |
| `browser_loop_done` | Worker loop completed successfully. |

These events flow to the TUI via the bridge's `subagent_progress` envelope.

## Usage Examples

### Via TUI/Bridge

When running `proxi` (interactive TUI), the orchestrator can delegate web tasks to the browser agent:

**User**: "Research the top 3 electric SUVs under $50k and summarize their specs."

**Orchestrator decision**:
```json
{
  "type": "sub_agent_call",
  "agent": "browser",
  "task": "Research the top 3 electric SUVs under $50k and summarize their specs.",
  "context_refs": {}
}
```

The browser agent will:
1. Select web tools (e.g., `fetch_webpage`, `web_search_mcp`).
2. Plan and execute tool calls to gather data.
3. Stream progress events to the TUI status bar.
4. Return a final `SubAgentResult` with summary and artifacts.

### Via CLI (One-shot)

```bash
uv run proxi-run "Find the cheapest flight to Tokyo next month"
```

If the orchestrator decides to delegate this to the browser agent, the flow is identical (but without TUI progress display).

## Configuration

### Enabling/Disabling

- Browser agent is **enabled by default** when sub-agents are enabled.
- To disable all sub-agents (including browser): `uv run proxi-run --no-sub-agents "task"`

### Tool Dependencies

The browser agent **requires at least one web-capable tool** to function. Options:

1. **MCP web tools**: Configure MCP servers in `config/mcporter.json` (e.g., `@modelcontextprotocol/server-web`).
2. **Custom tools**: Register tools with web-related keywords in their name/description.

If no web tools are available, the agent fails fast with:
```
Error: No web tools available in registry.
Suggestions: Configure an MCP web or browser server, or register custom web tools.
```

## Testing

Tests are in [tests/test_browser_subagent.py](../tests/test_browser_subagent.py). Run:

```bash
uv run pytest tests/test_browser_subagent.py -v
```

Test coverage:
- Tool selection (web vs non-web keywords)
- Execution flow (tool call → respond decision)
- Error handling (no web tools, timeout)
- Progress event emission

## Future Enhancements

1. **Session persistence**: Store browser state/cookies across calls.
2. **Advanced planning**: Multi-step plan generation before execution.
3. **Domain safety policies**: Enforce allow/deny lists for URLs.
4. **Download size limits**: Cap file/resource downloads.
5. **Parallel tool execution**: Fork multiple browser actions simultaneously.
6. **MCP stdio boundary**: Run browser agent as standalone MCP server process.

## Architecture Summary

```
Main Orchestrator (proxi/core/loop.py)
  ↓
  [SUB_AGENT_CALL decision: agent="browser"]
  ↓
SubAgentManager.run("browser", context)
  ↓
BrowserSubAgent.run(context)
  ↓
  [Turn 1] LLM → TOOL_CALL(fetch_webpage) → ToolRegistry.execute()
  [Turn 2] LLM → TOOL_CALL(web_search) → ToolRegistry.execute()
  [Turn 3] LLM → RESPOND("Summary: ...") → Return SubAgentResult
  ↓
Main Orchestrator receives result
  ↓
User sees final response in TUI
```

## Key Files

| File | Purpose |
|------|---------|
| [proxi/agents/browser.py](../proxi/agents/browser.py) | BrowserSubAgent implementation |
| [proxi/cli/main.py](../proxi/cli/main.py) | Registration in `setup_sub_agents()` |
| [proxi/core/loop.py](../proxi/core/loop.py) | Orchestrator routing and progress hook injection |
| [tests/test_browser_subagent.py](../tests/test_browser_subagent.py) | Unit tests |
| [docs/browser_subagent.md](browser_subagent.md) | This document |

## Related Documentation

- [README.md](../README.md) - Main project overview
- [proxi/agents/base.py](../proxi/agents/base.py) - SubAgent protocol
- [proxi/agents/summarizer.py](../proxi/agents/summarizer.py) - Example sub-agent
