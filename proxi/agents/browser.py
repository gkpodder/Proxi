"""Browser automation sub-agent adapter."""

import os
import sys
import uuid
from pathlib import Path
from typing import Any

from proxi.agents.base import AgentContext, BaseSubAgent, SubAgentResult
from proxi.observability.logging import get_logger

# Add browser-subagent to Python path
_BROWSER_SUBAGENT_PATH = Path(__file__).parent.parent.parent / "browser-subagent"
if str(_BROWSER_SUBAGENT_PATH) not in sys.path:
    sys.path.insert(0, str(_BROWSER_SUBAGENT_PATH))

# Import browser-subagent components
from app.agent import Agent as BrowserAgentCore
from app.llm_client import OpenAIClient as BrowserOpenAIClient
from app.models import RunResult, TaskSpec
from app.security import ArtifactManager, SecurityValidator

logger = get_logger(__name__)


class BrowserAgent(BaseSubAgent):
    """Browser automation sub-agent for proxi."""

    def __init__(
        self,
        headless: bool = True,
        max_steps: int = 20,
        allowed_domains: list[str] | None = None,
        denied_domains: list[str] | None = None,
        artifacts_base_dir: str | Path = "./browser_artifacts",
    ):
        """
        Initialize browser agent.

        Args:
            headless: Run browser in headless mode
            max_steps: Maximum browser steps per task
            allowed_domains: List of allowed domains (empty = allow all)
            denied_domains: List of denied domains
            artifacts_base_dir: Directory for storing browser artifacts
        """
        super().__init__(
            name="browser",
            description=(
                "Automated web browser for navigating websites, clicking elements, "
                "filling forms, extracting data, and performing multi-step web interactions. "
                "Use for: web scraping, form submission, search queries, data extraction, "
                "and any task requiring web browsing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "start_url": {
                        "type": "string",
                        "description": "Starting URL to navigate to (optional)",
                    },
                    "extract_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific fields to extract from web pages (optional)",
                    },
                },
            },
            system_prompt="",  # Not used by browser agent
        )

        self.headless = headless
        self.max_steps = max_steps
        self.artifacts_base_dir = Path(artifacts_base_dir)

        # Initialize browser components
        self.security_validator = SecurityValidator(
            allowed_domains=allowed_domains or [],
            denied_domains=denied_domains or [],
            block_private_ips=True,
        )

        self.artifact_manager = ArtifactManager(
            base_dir=self.artifacts_base_dir,
            max_download_size_mb=10,
        )

        # Create OpenAI client for browser agent
        # Browser agent uses its own client for now
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable required for browser agent")

        self.browser_llm_client = BrowserOpenAIClient(
            api_key=api_key,
            model="gpt-4o-mini",
        )

        # Initialize browser agent core
        self.browser_core = BrowserAgentCore(
            llm_client=self.browser_llm_client,
            security_validator=self.security_validator,
            artifact_manager=self.artifact_manager,
            max_steps=self.max_steps,
            headless=self.headless,
            keep_browser_open=False,
        )

        logger.info(
            "browser_agent_initialized",
            headless=headless,
            max_steps=max_steps,
            artifacts_dir=str(self.artifacts_base_dir),
        )

    async def run(
        self,
        context: AgentContext,
        max_turns: int = 10,
        max_tokens: int = 2000,
        max_time: float = 30.0,
    ) -> SubAgentResult:
        """
        Run browser automation task.

        Args:
            context: Agent context with task and references
            max_turns: Maximum number of turns (mapped to browser steps)
            max_tokens: Maximum tokens (not directly used by browser agent)
            max_time: Maximum time in seconds

        Returns:
            Sub-agent result with browser execution details
        """
        logger.info(
            "browser_agent_run_start",
            task=context.task,
            max_turns=max_turns,
            max_time=max_time,
        )

        # Map max_turns to browser steps
        # Browser agent uses steps, proxi uses turns
        effective_max_steps = min(max_turns, self.max_steps)

        # Build TaskSpec from AgentContext
        task_spec = self._build_task_spec(
            context=context,
            max_steps=effective_max_steps,
            max_time=max_time,
        )

        try:
            # Execute browser task
            result: RunResult = await self.browser_core.run_task(task_spec)

            # Map RunResult to SubAgentResult
            sub_agent_result = self._map_result(result)

            logger.info(
                "browser_agent_run_complete",
                success=sub_agent_result.success,
                confidence=sub_agent_result.confidence,
                steps_taken=result.steps_taken,
            )

            return sub_agent_result

        except Exception as e:
            logger.error(
                "browser_agent_run_error",
                error=str(e),
                exc_info=True,
            )
            return SubAgentResult(
                summary=f"Browser agent error: {str(e)}",
                artifacts={},
                confidence=0.0,
                success=False,
                error=str(e),
                follow_up_suggestions=[],
            )

    def _build_task_spec(
        self,
        context: AgentContext,
        max_steps: int,
        max_time: float,
    ) -> TaskSpec:
        """Build browser TaskSpec from AgentContext."""
        # Generate request ID
        request_id = str(uuid.uuid4())

        # Extract inputs from context_refs
        inputs: dict[str, Any] = {}
        if isinstance(context.context_refs, dict):
            # Look for start_url in context_refs
            if "start_url" in context.context_refs:
                inputs["start_url"] = context.context_refs["start_url"]
            # Include any other inputs
            if "inputs" in context.context_refs:
                inputs.update(context.context_refs["inputs"])

        # Build constraints
        constraints = {
            "max_time": max_time,
            "max_steps": max_steps,
        }

        # Extract state for resumption if present
        state = context.context_refs.get("state") if isinstance(context.context_refs, dict) else None

        return TaskSpec(
            task=context.task,
            context={
                "history_snapshot": context.history_snapshot,
                **context.context_refs,
            },
            inputs=inputs,
            constraints=constraints,
            state=state,
            request_id=request_id,
        )

    def _map_result(self, result: RunResult) -> SubAgentResult:
        """Convert browser RunResult to SubAgentResult."""
        # Build summary message
        if result.success and result.done:
            summary = (
                f"Successfully completed browser task in {result.steps_taken} steps. "
                f"Final URL: {result.final_url}"
            )
        elif result.success and result.needs_input:
            summary = (
                f"Browser task needs additional input after {result.steps_taken} steps. "
                f"Final URL: {result.final_url}"
            )
        elif result.success:
            summary = (
                f"Browser task incomplete after {result.steps_taken} steps. "
                f"Final URL: {result.final_url}"
            )
        else:
            summary = f"Browser task failed: {result.error}"

        # Build artifacts dictionary
        artifacts = {
            "request_id": result.request_id,
            "final_url": result.final_url,
            "steps_taken": result.steps_taken,
            "result_data": result.result_data or {},
            "state": result.state or {},
            "artifact_files": result.artifacts,
            "done": result.done,
            "needs_input": result.needs_input,
        }

        # Calculate confidence score
        if result.success and result.done:
            confidence = 0.95
        elif result.success and result.needs_input:
            confidence = 0.7
        elif result.success:
            confidence = 0.5
        else:
            confidence = 0.1

        # Build follow-up suggestions
        follow_ups: list[str] = []
        if result.needs_input:
            follow_ups.append("Provide additional input to continue browser task")
        if not result.done and result.success:
            follow_ups.append(
                "Task incomplete - consider resuming from state or adjusting constraints"
            )
        if result.result_data:
            follow_ups.append("Extracted data available in artifacts.result_data")

        return SubAgentResult(
            summary=summary,
            artifacts=artifacts,
            confidence=confidence,
            success=result.success,
            error=result.error,
            follow_up_suggestions=follow_ups,
        )
