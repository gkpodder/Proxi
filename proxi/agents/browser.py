"""Browser sub-agent for web-focused tasks.

Fresh implementation intended to run as an isolated worker inside Proxi's
sub-agent system. This version is tool-driven: it plans and executes browser/
web actions by calling registered web-capable tools.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from proxi.agents.base import AgentContext, BaseSubAgent, SubAgentResult
from proxi.core.state import Message
from proxi.llm.base import LLMClient
from proxi.llm.vision_verifier import VisionVerifier, VisionPlanner
from proxi.llm.schemas import DecisionType, ToolSpec
from proxi.observability.logging import get_logger
from proxi.tools.registry import ToolRegistry

logger = get_logger(__name__)


class WorkflowPlanner:
    """Decomposes high-level web tasks into structured sub-goals."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
    
    async def decompose(self, task: str) -> dict[str, Any]:
        """
        Decompose a high-level task into structured workflow steps.
        
        Returns dict with:
            - steps: List of step descriptions
            - workflow_type: Type of workflow (search, form_fill, scrape, navigate, etc)
            - estimated_complexity: low|medium|high
        """
        prompt = (
            "You are a web automation planner. Given a high-level task, decompose it into "
            "specific, actionable steps. Return ONLY valid JSON with keys: "
            "steps (array of strings), workflow_type (string), estimated_complexity (low|medium|high). "
            "Be specific about navigation, obstacle handling, input filling, and result extraction."
        )
        
        user_message = (
            f"Task: {task}\n\n"
            "Decompose this into ordered steps. Consider:\n"
            "1. Initial navigation and obstacle dismissal (cookies, popups)\n"
            "2. Page analysis to discover forms/inputs\n"
            "3. Sequential interactions (fill, click, wait)\n"
            "4. Result extraction and verification\n"
            "Return JSON only."
        )
        
        try:
            response = await self.llm_client.generate(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=user_message),
                ],
                tools=[],
                temperature=0.3,
            )
            
            # Parse response content as JSON
            content = response.text.strip()
            if content:
                # Try to extract JSON from response
                if "{" in content:
                    json_start = content.index("{")
                    json_end = content.rindex("}") + 1
                    json_str = content[json_start:json_end]
                    parsed = json.loads(json_str)
                    
                    return {
                        "steps": parsed.get("steps", []),
                        "workflow_type": parsed.get("workflow_type", "unknown"),
                        "estimated_complexity": parsed.get("estimated_complexity", "medium"),
                    }
        except Exception as e:
            logger.warning(f"Workflow planning failed: {e}")
        
        # Fallback: simple heuristic decomposition
        steps = []
        task_lower = task.lower()
        
        if "search" in task_lower or "find" in task_lower:
            steps = [
                "Navigate to target website",
                "Dismiss any cookie banners or popups (automatic)",
                "Use browser_analyze_page to discover search input field",
                "Fill search input using discovered selector",
                "Use browser_analyze_page to find submit button",
                "Click submit button using discovered selector",
                "Wait for results to load",
                "Extract relevant information",
            ]
            workflow_type = "search"
        elif "book" in task_lower or "reserve" in task_lower or "form" in task_lower:
            steps = [
                "Navigate to target website",
                "Handle initial popups/modals (automatic)",
                "Use browser_analyze_page to discover form structure",
                "Fill required fields using discovered selectors",
                "Handle date pickers or dropdowns",
                "Use browser_analyze_page to find submit button",
                "Submit form",
                "Verify submission success",
            ]
            workflow_type = "form_fill"
        elif "extract" in task_lower or "scrape" in task_lower:
            steps = [
                "Navigate to target URL",
                "Wait for content to load",
                "Dismiss obstacles (automatic)",
                "Use browser_analyze_page to understand content structure",
                "Extract text from page elements",
                "Verify extracted data",
            ]
            workflow_type = "scrape"
        else:
            steps = [
                "Navigate to destination",
                "Use browser_analyze_page to understand page structure",
                "Execute required interactions based on analysis",
                "Extract results",
            ]
            workflow_type = "generic"
        
        return {
            "steps": steps,
            "workflow_type": workflow_type,
            "estimated_complexity": "medium",
        }


class BrowserSubAgent(BaseSubAgent):
    """Specialized sub-agent for browser and web workflows."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        *,
        vision_verifier: VisionVerifier | None = None,
        vision_planner: VisionPlanner | None = None,
        max_vision_checks: int = 6,
        use_vision_planning: bool = True,
    ):
        super().__init__(
            name="browser",
            description=(
                "Executes web tasks in an isolated browser-worker loop: research, "
                "scraping, form workflows, monitoring checks, and travel/shopping discovery."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Web task to execute.",
                    },
                    "context_refs": {
                        "type": "object",
                        "description": "Optional execution options/context.",
                        "additionalProperties": True,
                    },
                },
                "required": ["task"],
            },
            system_prompt=(
                "You are BrowserSubAgent with vision-guided planning. "
                "After navigating or taking actions, a vision AI analyzes screenshots and suggests next steps. "
                "\n\n"
                "CRITICAL INSTRUCTION: When you receive vision guidance (🔮), you MUST follow it EXACTLY:\n"
                "- If vision suggests browser_fill with text_hint='Where are you going?', use browser_fill with selector='Where are you going?' (text-based!)\n"
                "- If vision suggests browser_click with text_hint='Search', use browser_click with selector='Search' (click visible text!)\n"
                "- DO NOT create your own CSS selectors like input[id='...'] - vision AI sees the actual page, trust its text hints\n"
                "- Text-based selectors (clicking/filling by visible text) are MORE RELIABLE than CSS selectors on modern sites\n"
                "\n"
                "Work step-by-step. After each action, vision AI will guide the next steps. "
                "Finish with a concise final response when vision AI marks task_complete=true or all actions done."
            ),
        )
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.vision_verifier = vision_verifier
        self.vision_planner = vision_planner
        self.max_vision_checks = max_vision_checks
        # Check if vision planning is truly enabled (planner exists and is enabled)
        self.use_vision_planning = (
            use_vision_planning 
            and vision_planner is not None 
            and getattr(vision_planner, 'enabled', False)
        )
        self.logger = logger
        
        if use_vision_planning and vision_planner and not getattr(vision_planner, 'enabled', False):
            logger.warning("vision_planning_disabled_planner_not_enabled")

    async def run(
        self,
        context: AgentContext,
        max_turns: int = 10,
        max_tokens: int = 2000,
        max_time: float = 30.0,
    ) -> SubAgentResult:
        """Run browser worker loop using available web tools."""
        start_time = time.time()
        session_id = f"browser-{uuid.uuid4()}"

        task = context.task.strip()
        if not task:
            return SubAgentResult(
                summary="Browser task is empty.",
                artifacts={"session_id": session_id},
                confidence=0.0,
                success=False,
                error="No browser task provided.",
            )

        progress_hook = self._extract_progress_hook(context)
        web_tools = self._select_web_tools()

        if not web_tools:
            return SubAgentResult(
                summary="Browser sub-agent has no web-capable tools configured.",
                artifacts={
                    "session_id": session_id,
                    "hint": "Connect MCP web/browser tools, then retry.",
                },
                confidence=0.0,
                success=False,
                error="No web tools available in registry.",
                follow_up_suggestions=[
                    "Configure an MCP web or browser server.",
                    "Retry after loading tools like fetch_webpage/open_simple_browser.",
                ],
            )

        # Use WorkflowPlanner to decompose task into structured steps
        planner = WorkflowPlanner(self.llm_client)
        workflow_plan = await planner.decompose(task)
        
        workflow_hint = ""
        if workflow_plan.get("steps"):
            steps_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(workflow_plan["steps"]))
            workflow_hint = (
                f"\n\nWorkflow Plan ({workflow_plan['workflow_type']} - "
                f"{workflow_plan['estimated_complexity']} complexity):\n{steps_list}\n"
                "Use this plan as guidance but adapt based on what you observe."
            )

        self._emit_progress(
            progress_hook,
            {
                "event": "browser_loop_start",
                "session_id": session_id,
                "task": task,
                "tool_count": len(web_tools),
                "workflow_plan": workflow_plan,
            },
        )

        messages: list[Message] = [
            Message(role="system", content=self.system_prompt),
            Message(
                role="user",
                content=(
                    f"Task: {task}\n"
                    "Execute this as a browser/web worker. Use tools where needed. "
                    "When complete, return a concise final summary."
                    f"{workflow_hint}"
                ),
            ),
        ]

        actions: list[dict[str, Any]] = []
        tokens_used = 0
        verification_checks = 0
        verification_failures = 0

        for turn in range(1, max_turns + 1):
            if time.time() - start_time > max_time:
                return self._timeout_result(
                    session_id=session_id,
                    actions=actions,
                    turns=turn - 1,
                    max_time=max_time,
                )

            self._emit_progress(
                progress_hook,
                {
                    "event": "browser_loop_turn",
                    "session_id": session_id,
                    "turn": turn,
                    "message": "Deciding next web action.",
                },
            )

            response = await self.llm_client.generate(messages=messages, tools=web_tools)
            decision = response.decision
            tokens_used += int(response.usage.get("total_tokens", 0))

            if decision.type == DecisionType.RESPOND:
                final_summary = decision.payload.get("content", "").strip() or self._build_action_summary(actions)
                self._emit_progress(
                    progress_hook,
                    {
                        "event": "browser_loop_done",
                        "session_id": session_id,
                        "turn": turn,
                        "message": "Browser task completed.",
                    },
                )
                return SubAgentResult(
                    summary=final_summary,
                    artifacts={
                        "session_id": session_id,
                        "actions": actions,
                        "tokens_used": tokens_used,
                        "task_type": self._infer_task_type(task),
                        "verification": {
                            "checks_used": verification_checks,
                            "checks_limit": self.max_vision_checks,
                            "failures": verification_failures,
                            "model": self.vision_verifier.model if self.vision_verifier else None,
                        },
                    },
                    confidence=0.82 if actions else 0.6,
                    success=True,
                    error=None,
                )

            if decision.type != DecisionType.TOOL_CALL:
                return SubAgentResult(
                    summary="Browser sub-agent received an unsupported decision type.",
                    artifacts={
                        "session_id": session_id,
                        "decision_type": decision.type.value,
                        "actions": actions,
                    },
                    confidence=0.0,
                    success=False,
                    error=f"Unsupported decision type: {decision.type.value}",
                )

            tool_name = str(decision.payload.get("name", ""))
            arguments = decision.payload.get("arguments", {})
            tool_call_id = str(decision.payload.get("id", f"browser-tool-{turn}"))

            if not isinstance(arguments, dict):
                arguments = {}

            if self._is_browser_action_tool(tool_name):
                arguments.setdefault("session_id", session_id)

            if not any(spec.name == tool_name for spec in web_tools):
                messages.append(
                    Message(
                        role="assistant",
                        content=(
                            f"Tool '{tool_name}' is not available to BrowserSubAgent. "
                            "Pick one of the provided web tools."
                        ),
                    )
                )
                continue

            self._emit_progress(
                progress_hook,
                {
                    "event": "browser_tool_start",
                    "session_id": session_id,
                    "turn": turn,
                    "tool": tool_name,
                    "arguments": arguments,
                },
            )

            messages.append(
                Message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                )
            )

            tool_result = await self.tool_registry.execute(tool_name, arguments)
            observation = (
                tool_result.output
                if tool_result.success
                else f"Tool failed: {tool_result.error or 'Unknown error'}"
            )
            
            # Add action-specific guidance for tool failures
            if not tool_result.success and self._is_browser_action_tool(tool_name):
                error_msg = tool_result.error or "Unknown error"
                retry_hint = ""
                
                if "timeout" in error_msg.lower():
                    retry_hint = (
                        "\n🔄 Timeout detected:\n"
                        "- Element may not exist or is hidden\n"
                        "- Try browser_analyze_page to verify page structure\n"
                        "- Increase timeout_ms parameter\n"
                        "- Use browser_wait_for to ensure element appears first"
                    )
                elif "selector" in error_msg.lower() or "not found" in error_msg.lower():
                    retry_hint = (
                        "\n🔄 Element not found:\n"
                        "- Use browser_analyze_page to discover available elements\n"
                        "- Try different selector strategies (text, aria-label, id)\n"
                        "- Element may be inside iframe or shadow DOM\n"
                        "- Page may not have loaded yet - wait first"
                    )
                elif "intercept" in error_msg.lower() or "obscured" in error_msg.lower():
                    retry_hint = (
                        "\n🔄 Element blocked:\n"
                        "- Cookie banner or modal is covering the element\n"
                        "- Try browser_press_key with 'Escape' to dismiss overlays\n"
                        "- Look for and click 'Accept' or 'Close' buttons first\n"
                        "- Use force=true parameter to force click"
                    )
                
                if retry_hint:
                    observation += retry_hint

            messages.append(
                Message(
                    role="tool",
                    name=tool_name,
                    tool_call_id=tool_call_id,
                    content=observation,
                )
            )

            actions.append(
                {
                    "turn": turn,
                    "tool": tool_name,
                    "arguments": arguments,
                    "success": tool_result.success,
                    "error": tool_result.error,
                }
            )

            if (
                tool_result.success
                and self._is_browser_action_tool(tool_name)
                and tool_name != "browser_screenshot"
                and self.vision_verifier is not None
                and verification_checks < self.max_vision_checks
            ):
                self._emit_progress(
                    progress_hook,
                    {
                        "event": "browser_verify_start",
                        "session_id": session_id,
                        "turn": turn,
                        "tool": tool_name,
                        "model": self.vision_verifier.model,
                    },
                )
                screenshot_result = await self.tool_registry.execute(
                    "browser_screenshot",
                    {"session_id": session_id, "full_page": False},
                )

                verification = None
                if screenshot_result.success:
                    image_base64 = str(screenshot_result.metadata.get("image_base64", ""))
                    if image_base64:
                        verification_checks += 1
                        verification = await self.vision_verifier.verify_action(
                            task=task,
                            session_id=session_id,
                            turn=turn,
                            tool_name=tool_name,
                            arguments=arguments,
                            observation=observation,
                            image_base64=image_base64,
                        )

                if verification:
                    actions[-1]["verification"] = {
                        "passed": verification.get("passed"),
                        "confidence": verification.get("confidence"),
                        "reason": verification.get("reason"),
                        "model": verification.get("model"),
                    }

                    self._emit_progress(
                        progress_hook,
                        {
                            "event": "browser_verify_done",
                            "session_id": session_id,
                            "turn": turn,
                            "tool": tool_name,
                            "passed": verification.get("passed"),
                            "confidence": verification.get("confidence"),
                            "model": verification.get("model"),
                        },
                    )

                    if not bool(verification.get("passed", True)):
                        verification_failures += 1
                        reason = str(verification.get("reason", "Action may have failed"))
                        hint = str(verification.get("next_step_hint", ""))
                        error_type = str(verification.get("error_type", "unknown"))
                        
                        # Generate actionable retry strategy based on error type
                        retry_strategy = self._get_retry_strategy(
                            tool_name=tool_name,
                            error_type=error_type,
                            arguments=arguments,
                        )
                        
                        warning_msg = (
                            f"⚠️ VERIFICATION FAILED for {tool_name}\n"
                            f"Reason: {reason}\n"
                            f"Error Type: {error_type}\n"
                        )
                        
                        if retry_strategy:
                            warning_msg += f"\n🔄 Suggested Retry Strategy:\n{retry_strategy}\n"
                        
                        if hint:
                            warning_msg += f"\n💡 Hint: {hint}\n"
                        
                        warning_msg += (
                            "\nOptions:\n"
                            "1. Try browser_analyze_page to discover elements\n"
                            "2. Use different selector strategy (text, aria-label, etc)\n"
                            "3. Wait longer for page state to stabilize\n"
                            "4. Check if obstacle (popup/modal) is blocking interaction"
                        )
                        
                        messages.append(
                            Message(
                                role="assistant",
                                content=warning_msg,
                            )
                        )

            self._emit_progress(
                progress_hook,
                {
                    "event": "browser_tool_done",
                    "session_id": session_id,
                    "turn": turn,
                    "tool": tool_name,
                    "success": tool_result.success,
                    "error": tool_result.error,
                },
            )
            
            # Vision-guided planning after key actions
            if (
                self.use_vision_planning
                and tool_result.success
                and self._is_browser_action_tool(tool_name)
                and tool_name in ["browser_navigate", "browser_click", "browser_fill"]
            ):
                try:
                    logger.info(f"vision_planning_triggered tool={tool_name}")
                    # Take screenshot and get vision AI guidance
                    screenshot_result = await self.tool_registry.execute(
                        "browser_screenshot",
                        {"session_id": session_id, "full_page": False},
                    )
                    
                    logger.info(f"vision_planning_screenshot success={screenshot_result.success}")
                    
                    if screenshot_result.success:
                        image_base64 = str(screenshot_result.metadata.get("image_base64", ""))
                        logger.info(f"vision_planning_image_size len={len(image_base64)} planner={self.vision_planner is not None}")
                        
                        if image_base64 and self.vision_planner:
                            completed_action_summaries = [
                                f"{a['tool']}({a.get('arguments', {})})"
                                for a in actions
                            ]
                            
                            page = await self.tool_registry.execute(
                                "browser_screenshot",
                                {"session_id": session_id},
                            )
                            page_url = page.metadata.get("url", "unknown") if page.success else "unknown"
                            
                            logger.info(f"vision_planning_calling_api url={page_url}")
                            vision_plan = await self.vision_planner.plan_next_actions(
                                task=task,
                                completed_actions=completed_action_summaries,
                                image_base64=image_base64,
                                page_url=page_url,
                            )
                            
                            logger.info(f"vision_planning_received actions={len(vision_plan.get('next_actions', []))}")
                            
                            # Log the actual suggestions for debugging
                            for action in vision_plan.get('next_actions', []):
                                logger.info(
                                    f"vision_suggestion tool={action.get('tool')} "
                                    f"text_hint='{action.get('text_hint', '')}' "
                                    f"value='{action.get('value', '')}' "
                                    f"desc='{action.get('description', '')}'"
                                )
                            
                            if vision_plan.get("next_actions"):
                                # Format actions with explicit examples showing exact tool calls
                                actions_with_examples = []
                                for i, action in enumerate(vision_plan["next_actions"], 1):
                                    tool = action.get('tool')
                                    text_hint = action.get('text_hint', '')
                                    value = action.get('value', '')
                                    desc = action.get('description', '')
                                    
                                    if tool == "browser_fill":
                                        example = f"browser_fill(selector='{text_hint}', value='{value}')"
                                    elif tool == "browser_click":
                                        example = f"browser_click(selector='{text_hint}')"
                                    else:
                                        example = f"{tool}(...)"
                                    
                                    actions_with_examples.append(
                                        f"  {i}. {desc}\n"
                                        f"     Execute: {example}"
                                    )
                                
                                next_actions_str = "\n".join(actions_with_examples)
                                
                                guidance_msg = (
                                    f"🔮 Vision AI analyzed the page and suggests:\n\n"
                                    f"Reasoning: {vision_plan.get('reasoning', '')}\n\n"
                                    f"Execute these actions in order:\n{next_actions_str}\n"
                                )
                                
                                if vision_plan.get("obstacles_visible"):
                                    guidance_msg += f"\nObstacles visible: {', '.join(vision_plan['obstacles_visible'])} (will be auto-cleared)\n"
                                
                                if vision_plan.get("task_complete"):
                                    guidance_msg += "\n✅ Task appears complete! Extract final results if needed.\n"
                                
                                messages.append(
                                    Message(
                                        role="assistant",
                                        content=guidance_msg,
                                    )
                                )
                                
                                # Emit vision guidance as progress event so user sees it
                                self._emit_progress(
                                    progress_hook,
                                    {
                                        "event": "vision_guidance",
                                        "session_id": session_id,
                                        "turn": turn,
                                        "reasoning": vision_plan.get("reasoning", ""),
                                        "next_actions": vision_plan.get("next_actions", []),
                                        "obstacles": vision_plan.get("obstacles_visible", []),
                                        "complete": vision_plan.get("task_complete", False),
                                    },
                                )
                                
                                logger.info(f"vision_planning_injected_guidance actions={len(vision_plan['next_actions'])}")
                except Exception as e:
                    logger.error(f"vision_planning_error error={str(e)}", exc_info=True)

            if tokens_used >= max_tokens:
                break

        summary = self._build_action_summary(actions)
        return SubAgentResult(
            summary=(
                "Browser sub-agent reached execution limits before explicit completion.\n"
                + summary
            ),
            artifacts={
                "session_id": session_id,
                "actions": actions,
                "tokens_used": tokens_used,
                "task_type": self._infer_task_type(task),
                "verification": {
                    "checks_used": verification_checks,
                    "checks_limit": self.max_vision_checks,
                    "failures": verification_failures,
                    "model": self.vision_verifier.model if self.vision_verifier else None,
                },
            },
            confidence=0.45 if actions else 0.0,
            success=False,
            error="Execution budget reached (turn/token/time limit).",
            follow_up_suggestions=["Increase max_turns or max_time and retry."],
        )

    def _select_web_tools(self) -> list[ToolSpec]:
        """Select likely web/browser-capable tools from the registry."""
        tool_specs = self.tool_registry.to_specs()
        web_keywords = {
            "web",
            "browser",
            "url",
            "http",
            "scrape",
            "search",
            "page",
            "site",
            "form",
            "monitor",
            "travel",
            "shopping",
            "fetch",
            "navigate",
        }

        selected: list[ToolSpec] = []
        for spec in tool_specs:
            haystack = f"{spec.name} {spec.description}".lower()
            if any(k in haystack for k in web_keywords):
                selected.append(spec)

        return selected

    def _infer_task_type(self, task: str) -> str:
        """Infer coarse task category for observability."""
        t = task.lower()
        if any(k in t for k in ("buy", "price", "cart", "checkout", "shop")):
            return "shopping"
        if any(k in t for k in ("form", "apply", "submit", "fill")):
            return "forms"
        if any(k in t for k in ("monitor", "watch", "track", "alert", "restock")):
            return "monitoring"
        if any(k in t for k in ("flight", "hotel", "trip", "travel", "itinerary")):
            return "travel"
        return "research"

    def _is_browser_action_tool(self, tool_name: str) -> bool:
        """Check whether the selected tool is a native browser action tool."""
        return tool_name.startswith("browser_")
    
    def _get_retry_strategy(
        self,
        tool_name: str,
        error_type: str,
        arguments: dict[str, Any],
    ) -> str:
        """Generate actionable retry strategy based on error type and tool."""
        strategies = {
            "selector_failed": {
                "browser_click": (
                    "- Try browser_analyze_page first to discover available buttons\n"
                    "- Use text parameter instead of selector for visible button text\n"
                    "- Try aria-label or data-testid attributes\n"
                    "- Check if element is inside an iframe"
                ),
                "browser_fill": (
                    "- Use browser_analyze_page to find input field details\n"
                    "- Try searching by placeholder text or label\n"
                    "- Verify the field is not hidden or disabled\n"
                    "- Click the field first before filling"
                ),
                "default": "Run browser_analyze_page to discover element selectors",
            },
            "element_obscured": {
                "browser_click": (
                    "- Element is blocked by overlay/popup\n"
                    "- Try browser_press_key with 'Escape' to close overlays\n"
                    "- Look for cookie banner accept button and click first\n"
                    "- Use force=true parameter to force click through overlays"
                ),
                "default": "Dismiss popups/modals before interacting with page elements",
            },
            "wrong_page": {
                "default": (
                    "- Verify navigation succeeded with browser_wait_for\n"
                    "- Check if redirected to unexpected page\n"
                    "- May need to handle authentication or region selection first"
                ),
            },
            "timing_issue": {
                "default": (
                    "- Page content still loading\n"
                    "- Use browser_wait_for before next action\n"
                    "- Increase timeout_ms parameter\n"
                    "- Wait for network idle before extracting data"
                ),
            },
        }
        
        tool_strategies = strategies.get(error_type, {})
        return tool_strategies.get(tool_name, tool_strategies.get("default", ""))

    def _extract_progress_hook(
        self,
        context: AgentContext,
    ) -> Callable[[dict[str, Any]], None] | None:
        """Extract optional loop progress callback from context."""
        hook = context.context_refs.get("__progress_hook__")
        return hook if callable(hook) else None

    def _emit_progress(
        self,
        hook: Callable[[dict[str, Any]], None] | None,
        payload: dict[str, Any],
    ) -> None:
        """Emit progress update if callback exists."""
        if not hook:
            return
        try:
            hook(payload)
        except Exception as e:
            self.logger.warning("browser_progress_hook_error", error=str(e))

    def _build_action_summary(self, actions: list[dict[str, Any]]) -> str:
        """Build concise summary from executed actions."""
        if not actions:
            return "No browser actions were executed."

        success_count = sum(1 for a in actions if a.get("success"))
        fail_count = len(actions) - success_count
        tool_list = ", ".join(dict.fromkeys(str(a.get("tool")) for a in actions))
        return (
            f"Executed {len(actions)} browser/web actions "
            f"({success_count} succeeded, {fail_count} failed). "
            f"Tools used: {tool_list}."
        )

    def _timeout_result(
        self,
        session_id: str,
        actions: list[dict[str, Any]],
        turns: int,
        max_time: float,
    ) -> SubAgentResult:
        """Build timeout result."""
        return SubAgentResult(
            summary=(
                f"Browser sub-agent timed out after {max_time:.2f}s "
                f"and {turns} turns.\n{self._build_action_summary(actions)}"
            ),
            artifacts={"session_id": session_id, "actions": actions, "turns": turns},
            confidence=0.2 if actions else 0.0,
            success=False,
            error=f"Browser execution exceeded max_time={max_time}",
        )
