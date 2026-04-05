"""BrowserSubAgent — autonomous browser agent powered by browser-use.

This sub-agent accepts a high-level task description (e.g. "find the cheapest
non-stop flight from SFO to NYC next Friday") and executes it autonomously
using the browser-use library.  browser-use runs its own internal LLM reasoning
loop, handles DOM parsing, vision, element finding, and multi-step planning —
the caller just provides a task and waits for the result.

The agent uses a dedicated Chrome profile at ~/.proxi/browser_profile/ so it
never touches the user's personal browser sessions.

Requirements
------------
    uv add browser-use && playwright install chromium
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from proxi.agents.base import AgentContext, BaseSubAgent, SubAgentResult
from proxi.observability.logging import get_logger
from proxi.security.key_store import get_key_value

logger = get_logger(__name__)

_PROFILE_DIR = Path.home() / ".proxi" / "browser_profile"

_SYSTEM_PROMPT = """You are an expert browser agent.  Your job is to complete
web-based tasks accurately and efficiently.  Common tasks include:
- Researching and comparing flights (Google Flights, Kayak, Expedia, etc.)
- Ordering food or groceries (DoorDash, Instacart, etc.)
- Finding the best price for a product across multiple vendors
- Filling forms, reading pages, and extracting structured information

Always confirm key details before submitting orders that involve purchases.
When you have completed the task, summarise what you found or did clearly."""


def _make_browser_use_llm() -> Any:
    """Create a browser-use native LLM from whichever API key is available.

    browser-use ships its own LLM wrappers (browser_use.llm.*) that expose
    the .provider attribute its agent requires.  We must NOT use LangChain's
    ChatOpenAI/ChatAnthropic here — those lack .provider and break Agent init.
    """
    anthropic_key = get_key_value("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            from browser_use.llm.anthropic.chat import (  # type: ignore[import-untyped]
                ChatAnthropic as BUChatAnthropic,
            )

            logger.info("browser_agent_llm", provider="anthropic")
            return BUChatAnthropic(
                api_key=anthropic_key,
                model="claude-3-5-sonnet-20241022",
            )
        except ImportError:
            logger.warning("browser_use_anthropic_llm_not_available")

    openai_key = get_key_value("OPENAI_API_KEY")
    if openai_key:
        try:
            from browser_use.llm.openai.chat import (  # type: ignore[import-untyped]
                ChatOpenAI as BUChatOpenAI,
            )

            logger.info("browser_agent_llm", provider="openai")
            return BUChatOpenAI(
                api_key=openai_key,
                model="gpt-4o",
            )
        except ImportError:
            logger.warning("browser_use_openai_llm_not_available")

    raise ValueError(
        "No LLM available for browser agent. "
        "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in the Proxi key store."
    )


class BrowserSubAgent(BaseSubAgent):
    """Autonomous browser agent for complex multi-step web tasks.

    Powered by the browser-use library which runs its own internal LLM loop
    with vision and DOM understanding.  Use this for tasks that require many
    steps, judgement calls, and page-to-page navigation.

    For simpler, fine-grained browser control use the individual browser_*
    tools (browser_navigate, browser_click, browser_snapshot, etc.) directly.
    """

    # Browser tasks (flights, groceries, price comparison) can take 10+ minutes.
    # This overrides BaseSubAgent.default_max_time so SubAgentManager never
    # kills the browser agent with an over-aggressive caller default.
    default_max_time: float = 600.0

    def __init__(self) -> None:
        super().__init__(
            name="browser",
            description=(
                "Autonomous browser agent for complex multi-step web tasks: "
                "research and compare flights, order food/groceries (DoorDash, Instacart), "
                "find the best price for a product across multiple vendors, "
                "fill out web forms, and extract information from websites. "
                "Provide a clear high-level task description; the agent handles all "
                "browser interactions internally."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "High-level description of what to accomplish in the browser. "
                            "Be specific: include dates, locations, product names, budget, etc."
                        ),
                    },
                    "start_url": {
                        "type": "string",
                        "description": (
                            "Optional starting URL (e.g. 'https://www.google.com/flights'). "
                            "If omitted the agent will navigate to an appropriate page itself."
                        ),
                    },
                    "max_steps": {
                        "type": "integer",
                        "description": "Maximum browser actions to take (default: 75).",
                    },
                },
                "required": ["task"],
            },
            system_prompt=_SYSTEM_PROMPT,
        )

    async def run(
        self,
        context: AgentContext,
        max_turns: int = 15,
        max_tokens: int = 8000,
        max_time: float = 600.0,
    ) -> SubAgentResult:
        """Execute the browser task using browser-use."""
        # Pull parameters from context
        task = context.context_refs.get("task") or context.task
        start_url: str | None = context.context_refs.get("start_url")  # type: ignore[assignment]
        max_steps = int(context.context_refs.get("max_steps", 75))

        if not task:
            return SubAgentResult(
                summary="No task provided",
                artifacts={},
                confidence=0.0,
                success=False,
                error="task parameter is required",
            )

        # Lazy import — browser-use is optional; give a clear error if missing.
        try:
            from browser_use import Agent  # type: ignore[import-untyped]
            from browser_use.browser.profile import BrowserProfile  # type: ignore[import-untyped]
        except ImportError:
            msg = (
                "browser-use is not installed. "
                "Run: uv add browser-use langchain-openai langchain-anthropic "
                "&& playwright install chromium"
            )
            logger.error("browser_use_not_installed")
            return SubAgentResult(
                summary=msg,
                artifacts={},
                confidence=0.0,
                success=False,
                error=msg,
            )

        try:
            llm = _make_browser_use_llm()
        except ValueError as exc:
            return SubAgentResult(
                summary=str(exc),
                artifacts={},
                confidence=0.0,
                success=False,
                error=str(exc),
            )

        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("browser_agent_starting", task=task[:120], max_steps=max_steps)

        try:
            browser_profile = BrowserProfile(
                headless=False,
                user_data_dir=str(_PROFILE_DIR),
            )

            full_task = task
            if start_url:
                full_task = f"Start at {start_url}\n\n{task}"

            agent = Agent(
                task=full_task,
                llm=llm,
                browser_profile=browser_profile,
                max_actions_per_step=5,
            )

            history = await asyncio.wait_for(
                agent.run(max_steps=max_steps),
                timeout=max_time,
            )

            final = history.final_result() or "Task completed (no explicit result returned)."
            urls_visited: list[str] = []
            try:
                urls_visited = [str(u) for u in history.urls() if u]
            except Exception:
                pass

            logger.info("browser_agent_done", final=final[:200])
            return SubAgentResult(
                summary=final,
                artifacts={
                    "final_result": final,
                    "urls_visited": urls_visited,
                    "steps_taken": history.number_of_steps(),
                },
                confidence=0.85,
                success=True,
                error=None,
                follow_up_suggestions=[
                    "Use browser_snapshot to inspect the current page state.",
                    "Use browser_navigate to visit another page.",
                ],
            )

        except asyncio.TimeoutError:
            msg = f"Browser task timed out after {max_time:.0f}s"
            logger.warning("browser_agent_timeout", timeout=max_time)
            return SubAgentResult(
                summary=msg,
                artifacts={},
                confidence=0.0,
                success=False,
                error=msg,
            )
        except Exception as exc:
            logger.error("browser_agent_error", error=str(exc), exc_info=True)
            return SubAgentResult(
                summary=f"Browser task failed: {exc}",
                artifacts={},
                confidence=0.0,
                success=False,
                error=str(exc),
            )
