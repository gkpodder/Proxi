"""BrowserSubAgent — autonomous browser agent powered by browser-use.

This sub-agent accepts a high-level task description (e.g. "find the cheapest
non-stop flight from SFO to NYC next Friday") and executes it autonomously
using the browser-use library.  browser-use runs its own internal LLM reasoning
loop, handles DOM parsing, vision, element finding, and multi-step planning —
the caller just provides a task and waits for the result.

The agent uses a dedicated Chrome profile at ~/.proxi/browser_profile/ so it
never touches the user's personal browser sessions.

Speed modes
-----------
fast=False (default)
    Full reasoning mode.  Uses Anthropic Claude or OpenAI GPT-4o with
    think-before-acting, plan evaluation, and a visible browser window so the
    user can monitor progress.  Best for accurate, high-stakes tasks.

fast=True
    Flash mode.  Uses Groq Llama (or Gemini Flash as fallback) with
    flash_mode=True which skips planning/evaluation steps and relies on direct
    action sequences.  Runs headless.  Best for quick lookups and simple tasks
    where speed matters more than deliberation.

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

# Extra instructions injected when fast=True to help flash-mode models
# stay on track without the planning layer.
_FAST_SPEED_PROMPT = """
Speed optimization instructions:
- Be extremely concise and direct.
- Get to the goal as quickly as possible using multi-action sequences.
- Skip exploratory steps — go straight to the target page.
- Do not narrate; just act and report the final result.
"""


# --------------------------------------------------------------------------- #
# LLM factory helpers                                                            #
# --------------------------------------------------------------------------- #


def _make_browser_use_llm() -> Any:
    """Create a browser-use native LLM for full-reasoning mode.

    Priority: Anthropic Claude (best accuracy) → OpenAI GPT-4o.

    browser-use ships its own LLM wrappers (browser_use.llm.*) that expose
    the .provider attribute its Agent requires.  Do NOT use LangChain models
    here — they lack .provider and break Agent.__init__.
    """
    anthropic_key = get_key_value("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            from browser_use.llm.anthropic.chat import (  # type: ignore[import-untyped]
                ChatAnthropic as BUChatAnthropic,
            )

            logger.info("browser_agent_llm", provider="anthropic", mode="full")
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

            logger.info("browser_agent_llm", provider="openai", mode="full")
            return BUChatOpenAI(api_key=openai_key, model="gpt-4o")
        except ImportError:
            logger.warning("browser_use_openai_llm_not_available")

    raise ValueError(
        "No LLM available for browser agent. "
        "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in the Proxi key store."
    )


def _make_fast_llm() -> Any:
    """Create the fastest available browser-use LLM for flash mode.

    Priority: Groq Llama (ultra-fast inference) → Google Gemini Flash
    → falls back to standard _make_browser_use_llm() if neither key exists.

    Groq provides near-instant token generation via their LPU hardware.
    Gemini Flash is Google's optimised speed tier.
    """
    groq_key = get_key_value("GROQ_API_KEY")
    if groq_key:
        try:
            from browser_use.llm.groq.chat import (  # type: ignore[import-untyped]
                ChatGroq as BUChatGroq,
            )

            logger.info("browser_agent_llm", provider="groq", mode="fast")
            return BUChatGroq(
                api_key=groq_key,
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
                temperature=0.0,
            )
        except ImportError:
            logger.warning("browser_use_groq_llm_not_available")

    google_key = get_key_value("GOOGLE_API_KEY")
    if google_key:
        try:
            from browser_use.llm.google.chat import (  # type: ignore[import-untyped]
                ChatGoogle as BUChatGoogle,
            )

            logger.info("browser_agent_llm", provider="google", mode="fast")
            return BUChatGoogle(api_key=google_key, model="gemini-2.0-flash")
        except ImportError:
            logger.warning("browser_use_google_llm_not_available")

    # No fast-tier key — fall back to standard model (still fast enough)
    logger.info(
        "browser_agent_fast_llm_fallback",
        reason="no GROQ_API_KEY or GOOGLE_API_KEY; using standard model",
    )
    return _make_browser_use_llm()


# --------------------------------------------------------------------------- #
# Sub-agent                                                                      #
# --------------------------------------------------------------------------- #


class BrowserSubAgent(BaseSubAgent):
    """Autonomous browser agent for complex multi-step web tasks.

    Powered by the browser-use library which runs its own internal LLM loop
    with vision and DOM understanding.  Use this for tasks that require many
    steps, judgement calls, and page-to-page navigation.

    For simpler, fine-grained browser control use the individual browser_*
    tools (browser_navigate, browser_click, browser_snapshot, etc.) directly.

    Pass fast=true in context_refs for flash mode (Groq/Gemini, headless,
    no planning steps) — much faster for simple lookups and research tasks.
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
                "browser interactions internally. "
                "Set fast=true for quick research tasks (uses Groq/Gemini + flash mode)."
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
                        "description": (
                            "Maximum browser actions to take "
                            "(default: 75 in full mode, 40 in fast mode)."
                        ),
                    },
                    "fast": {
                        "type": "boolean",
                        "description": (
                            "Enable flash mode for maximum speed: uses Groq Llama or Gemini "
                            "Flash, runs headless, skips planning/evaluation steps. "
                            "Best for simple research. Default: false."
                        ),
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
        fast = bool(context.context_refs.get("fast", False))

        # Fast mode uses fewer steps; caller can override in either direction.
        default_steps = 40 if fast else 75
        max_steps = int(context.context_refs.get("max_steps", default_steps))

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
            msg = "browser-use is not installed. Run: uv add browser-use && playwright install chromium"
            logger.error("browser_use_not_installed")
            return SubAgentResult(
                summary=msg,
                artifacts={},
                confidence=0.0,
                success=False,
                error=msg,
            )

        try:
            llm = _make_fast_llm() if fast else _make_browser_use_llm()
        except ValueError as exc:
            return SubAgentResult(
                summary=str(exc),
                artifacts={},
                confidence=0.0,
                success=False,
                error=str(exc),
            )

        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(
            "browser_agent_starting",
            task=task[:120],
            max_steps=max_steps,
            fast=fast,
        )

        try:
            if fast:
                browser_profile = BrowserProfile(
                    headless=True,
                    user_data_dir=str(_PROFILE_DIR),
                    minimum_wait_page_load_time=0.1,
                    wait_for_network_idle_page_load_time=0.5,
                    wait_between_actions=0.1,
                )
            else:
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
                flash_mode=fast,
                max_actions_per_step=10 if fast else 5,
                extend_system_message=_FAST_SPEED_PROMPT if fast else None,
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

            logger.info("browser_agent_done", final=final[:200], fast=fast)
            return SubAgentResult(
                summary=final,
                artifacts={
                    "final_result": final,
                    "urls_visited": urls_visited,
                    "steps_taken": history.number_of_steps(),
                    "fast_mode": fast,
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
            logger.warning("browser_agent_timeout", timeout=max_time, fast=fast)
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
