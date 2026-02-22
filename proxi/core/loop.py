"""Main agent loop implementation."""

import json
import time
from typing import Any, Protocol

from proxi.agents.registry import SubAgentManager
from proxi.core.planner import Planner
from proxi.core.reflection import Reflector
from proxi.core.state import AgentState, AgentStatus, Message, TurnState, TurnStatus, WorkspaceConfig
from proxi.llm.base import LLMClient
from proxi.llm.schemas import DecisionType, ModelDecision, ToolCall
from proxi.observability.logging import get_logger
from proxi.observability.tracing import TraceContext
from proxi.tools.registry import ToolRegistry

logger = get_logger(__name__)


class BridgeEmitter(Protocol):
    """Protocol for emitting bridge messages (e.g. to TUI)."""

    def emit(self, msg: dict[str, Any]) -> None:
        """Emit a JSON-serializable message."""
        ...


class FormBridge(Protocol):
    """Protocol for requesting structured form input from the user."""

    async def request_form(
        self,
        tool_call_id: str,
        form_request: Any,  # FormRequest
    ) -> dict[str, Any]:
        """Emit user_input_required and await user_input_response. Returns raw payload."""
        ...


class AgentLoop:
    """Main agent loop controller."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        sub_agent_manager: SubAgentManager | None = None,
        max_turns: int = 50,
        enable_reflection: bool = True,
        emitter: BridgeEmitter | None = None,
        form_bridge: FormBridge | None = None,
        workspace: WorkspaceConfig | None = None,
    ):
        """Initialize the agent loop."""
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.sub_agent_manager = sub_agent_manager
        self.planner = Planner(llm_client)
        self.reflector = Reflector(enabled=enable_reflection)
        self.max_turns = max_turns
        self.emitter = emitter
        self.form_bridge = form_bridge
        self.logger = logger
        self.workspace = workspace

    async def run(self, initial_message: str) -> AgentState:
        """
        Run the agent loop with an initial message.

        Args:
            initial_message: Initial user message

        Returns:
            Final agent state
        """
        state = AgentState(
            status=AgentStatus.RUNNING,
            max_turns=self.max_turns,
            start_time=time.time(),
            workspace=self.workspace,
        )
        state.add_message(Message(role="user", content=initial_message))
        self.logger.info("agent_loop_start", message=initial_message[:100])
        return await self._run_loop(state)

    async def run_continue(self, state: AgentState, user_message: str) -> AgentState:
        """
        Continue the agent loop with another user message (e.g. for multi-turn chat).

        Args:
            state: Previous agent state (will be mutated)
            user_message: Next user message

        Returns:
            Updated agent state
        """
        state.add_message(Message(role="user", content=user_message))
        state.status = AgentStatus.RUNNING
        if state.end_time is not None:
            state.end_time = None
        self.logger.info("agent_loop_continue", message=user_message[:100])
        return await self._run_loop(state)

    async def _run_loop(self, state: AgentState) -> AgentState:
        """Inner loop: run until completion or failure."""
        try:
            with TraceContext("agent_loop"):
                while state.can_continue():
                    state.current_turn += 1
                    turn = TurnState(
                        turn_number=state.current_turn,
                        status=TurnStatus.PENDING,
                        start_time=time.time(),
                    )
                    state.add_turn(turn)

                    self.logger.debug("turn_start", turn=state.current_turn)

                    try:
                        # REASON → DECIDE
                        turn.status = TurnStatus.DECIDING
                        decision, usage = await self._decide(state, emit_stream=self.emitter is not None)

                        # Accumulate token usage
                        state.total_tokens += usage.get("total_tokens", 0)
                        turn.tokens_used = usage.get("total_tokens", 0)

                        # ACT
                        turn.status = TurnStatus.ACTING
                        turn.decision = decision.model_dump()

                        # If this is a tool call, we need to add the assistant message with tool_calls first
                        # This is required by OpenAI API - tool messages must follow assistant messages with tool_calls
                        if decision.type == DecisionType.TOOL_CALL:
                            # Check if there are multiple tool_calls
                            tool_calls = decision.payload.get("tool_calls")
                            # If tool_calls is None or empty, use a single-item list with the current decision
                            if not tool_calls:
                                tool_calls = [{
                                    "id": decision.payload.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": decision.payload.get("name", ""),
                                        "arguments": json.dumps(decision.payload.get("arguments", {})),
                                    }
                                }]

                            if len(tool_calls) > 1:
                                # Multiple tool calls - execute all of them
                                # Add assistant message with all tool_calls
                                state.add_message(
                                    Message(
                                        role="assistant",
                                        content=None,  # Must be None when tool_calls is present
                                        tool_calls=tool_calls,
                                    )
                                )

                                # Execute all tool calls
                                action_results = []
                                for tool_call in tool_calls:
                                    tool_call_id = tool_call.get("id")
                                    tool_name = tool_call.get(
                                        "function", {}).get("name")
                                    tool_args_str = tool_call.get(
                                        "function", {}).get("arguments", "{}")
                                    # Parse JSON arguments
                                    try:
                                        tool_args = json.loads(tool_args_str) if isinstance(
                                            tool_args_str, str) else tool_args_str
                                    except json.JSONDecodeError:
                                        tool_args = {}

                                    # Create a temporary decision for this tool call
                                    temp_decision = ModelDecision.tool_call(
                                        ToolCall(
                                            id=tool_call_id,
                                            name=tool_name,
                                            arguments=tool_args,
                                        ),
                                        reasoning=None,
                                    )

                                    # Execute the tool
                                    result = await self._act(state, temp_decision, turn)
                                    action_results.append({
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                        "result": result,
                                    })

                                # Add all tool response messages
                                for action_result in action_results:
                                    observation = self._observe(
                                        action_result["result"])
                                    state.add_message(
                                        Message(
                                            role="tool",
                                            content=observation,
                                            name=action_result["name"],
                                            tool_call_id=action_result["tool_call_id"],
                                        )
                                    )

                                # Set observation to combined results
                                turn.status = TurnStatus.OBSERVING
                                turn.action_result = {
                                    "type": "multiple_tool_calls", "results": action_results}
                                turn.observation = "\n".join(
                                    [self._observe(r["result"]) for r in action_results])
                            else:
                                # Single tool call - original behavior
                                state.add_message(
                                    Message(
                                        role="assistant",
                                        content=None,  # Must be None when tool_calls is present
                                        tool_calls=tool_calls,
                                    )
                                )

                                action_result = await self._act(state, decision, turn)

                                # OBSERVE
                                turn.status = TurnStatus.OBSERVING
                                turn.action_result = action_result
                                observation = self._observe(action_result)
                                turn.observation = observation

                                # Add tool response
                                tool_call_id = decision.payload.get("id", "")
                                state.add_message(
                                    Message(
                                        role="tool",
                                        content=observation,
                                        name=decision.payload.get("name"),
                                        tool_call_id=tool_call_id,
                                    )
                                )
                        else:
                            # Not a tool call, proceed normally
                            action_result = await self._act(state, decision, turn)

                            # OBSERVE
                            turn.status = TurnStatus.OBSERVING
                            turn.action_result = action_result
                            observation = self._observe(action_result)
                            turn.observation = observation

                            # Add message for non-tool decisions
                            if decision.type == DecisionType.SUB_AGENT_CALL:
                                state.add_message(
                                    Message(
                                        role="assistant",
                                        content=observation,
                                    )
                                )

                        # REFLECT
                        turn.status = TurnStatus.REFLECTING
                        reflection = await self.reflector.reflect(state, turn)
                        if reflection:
                            turn.reflection = reflection
                            self.logger.debug(
                                "reflection", turn=state.current_turn, reflection=reflection)

                        turn.status = TurnStatus.COMPLETED

                        # Check if we should stop
                        if decision.type == DecisionType.RESPOND:
                            state.status = AgentStatus.COMPLETED
                            final_content = decision.payload.get("content", "")
                            state.add_message(
                                Message(role="assistant", content=final_content))
                            break

                    except Exception as e:
                        turn.status = TurnStatus.ERROR
                        turn.error = str(e)
                        self.logger.error(
                            "turn_error", turn=state.current_turn, error=str(e))

                        if not self.reflector.should_retry(state, turn):
                            state.status = AgentStatus.FAILED
                            break

                    finally:
                        turn.end_time = time.time()

        except Exception as e:
            self.logger.error("agent_loop_error", error=str(e))
            state.status = AgentStatus.FAILED

        finally:
            state.end_time = time.time()
            if state.status == AgentStatus.RUNNING:
                state.status = AgentStatus.COMPLETED

        self.logger.info(
            "agent_loop_end",
            status=state.status.value,
            turns=state.current_turn,
            duration=state.end_time - state.start_time if state.start_time and state.end_time else 0,
        )
        return state

    async def _decide(
        self, state: AgentState, *, emit_stream: bool = False
    ) -> tuple[ModelDecision, dict[str, int]]:
        """Make a decision based on current state."""
        tools = self.tool_registry.to_specs()
        agents = None
        if self.sub_agent_manager:
            agents = self.sub_agent_manager.registry.to_specs()

        async def stream_callback(chunk: str) -> None:
            if self.emitter:
                self.emitter.emit({"type": "text_stream", "content": chunk})

        stream_cb = stream_callback if emit_stream else None
        decision, usage = await self.planner.decide(
            state, tools, agents, stream_callback=stream_cb
        )
        return decision, usage

    async def _act(
        self, state: AgentState, decision: ModelDecision, turn: TurnState
    ) -> dict[str, Any]:
        """Execute an action based on the decision."""
        if decision.type == DecisionType.TOOL_CALL:
            payload = decision.payload
            tool_name = payload.get("name")
            tool_call_id = payload.get("id", "")
            arguments = payload.get("arguments", {})

            # Intercept show_collaborative_form — never execute via registry
            if tool_name == "show_collaborative_form":
                return await self._handle_show_collaborative_form(
                    state, tool_call_id, arguments, turn
                )

            self.logger.info("tool_call", tool=tool_name,
                             turn=turn.turn_number)
            if self.emitter:
                self.emitter.emit({
                    "type": "tool_start",
                    "tool": tool_name,
                    "arguments": arguments,
                })
                self.emitter.emit({
                    "type": "status_update",
                    "label": f"Tool: {tool_name}",
                    "status": "running",
                })

            result = await self.tool_registry.execute(tool_name, arguments)

            if self.emitter:
                if result.output:
                    first_line = result.output.strip().split("\n")[0].strip()
                    if first_line and len(first_line) <= 100:
                        self.emitter.emit({
                            "type": "tool_log",
                            "content": first_line,
                        })
                self.emitter.emit({
                    "type": "tool_done",
                    "tool": tool_name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                })
                self.emitter.emit({
                    "type": "status_update",
                    "label": f"Tool: {tool_name}",
                    "status": "done",
                })

            return {
                "type": "tool_call",
                "tool": tool_name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "metadata": result.metadata,
            }

        elif decision.type == DecisionType.SUB_AGENT_CALL:
            if not self.sub_agent_manager:
                return {
                    "type": "sub_agent_call",
                    "error": "Sub-agent manager not available",
                }

            payload = decision.payload
            agent_name = payload.get("agent")
            task = payload.get("task", "")
            context_refs_list = payload.get("context_refs", [])

            # Build context from state
            from proxi.agents.base import AgentContext

            # Get relevant context references from state
            context_refs = {}
            for ref_id in context_refs_list:
                if ref_id in state.context_refs:
                    context_refs[ref_id] = state.context_refs[ref_id]

            context = AgentContext(
                task=task,
                context_refs=context_refs,
                history_snapshot=[msg.model_dump()
                                  # Last 5 messages
                                  for msg in state.history[-5:]],
            )

            self.logger.debug(
                "sub_agent_call",
                agent=agent_name,
                turn=turn.turn_number,
            )
            if self.emitter:
                self.emitter.emit({
                    "type": "subagent_start",
                    "agent": agent_name,
                    "task": task,
                })
                self.emitter.emit({
                    "type": "status_update",
                    "label": f"Subagent {agent_name} is thinking...",
                    "status": "running",
                })

            result = await self.sub_agent_manager.run(
                agent_name=agent_name,
                context=context,
                max_turns=10,  # Default budgets for sub-agents
                max_tokens=2000,
                max_time=30.0,
            )

            if self.emitter:
                self.emitter.emit({
                    "type": "subagent_done",
                    "agent": agent_name,
                    "success": result.success,
                })
                self.emitter.emit({
                    "type": "status_update",
                    "label": f"Subagent {agent_name}",
                    "status": "done",
                })

            return {
                "type": "sub_agent_call",
                "agent": agent_name,
                "success": result.success,
                "summary": result.summary,
                "artifacts": result.artifacts,
                "confidence": result.confidence,
                "error": result.error,
                "follow_up_suggestions": result.follow_up_suggestions,
            }

        elif decision.type == DecisionType.RESPOND:
            return {
                "type": "respond",
                "content": decision.payload.get("content", ""),
            }

        else:
            return {
                "type": "unknown",
                "error": f"Unknown decision type: {decision.type}",
            }

    async def _handle_show_collaborative_form(
        self,
        state: AgentState,
        tool_call_id: str,
        arguments: dict[str, Any] | str,
        turn: TurnState,
    ) -> dict[str, Any]:
        """Intercept show_collaborative_form: validate, emit to TUI, await response."""
        from pydantic import ValidationError

        from proxi.interaction.models import FormResponse
        from proxi.interaction.tool import parse_form_tool_call

        args_str = (
            json.dumps(arguments)
            if isinstance(arguments, dict)
            else str(arguments or "{}")
        )
        try:
            form_request = parse_form_tool_call(args_str)
        except (ValidationError, json.JSONDecodeError) as e:
            return {
                "type": "tool_call",
                "tool": "show_collaborative_form",
                "success": False,
                "output": "",
                "error": f"Schema validation error — fix and retry:\n{e}",
                "metadata": {},
            }

        if self.form_bridge is None:
            return {
                "type": "tool_call",
                "tool": "show_collaborative_form",
                "success": False,
                "output": "",
                "error": "Form input not available in headless mode. Use TUI/bridge to enable collaborative forms.",
                "metadata": {},
            }

        self.logger.info("form_request", goal=form_request.goal)
        if self.emitter:
            self.emitter.emit({
                "type": "status_update",
                "label": "Awaiting user input",
                "status": "running",
            })

        raw_response = await self.form_bridge.request_form(
            tool_call_id, form_request
        )
        form_response = FormResponse(
            answers=raw_response.get("answers", {}),
            skipped=raw_response.get("skipped", False),
            form_goal=form_request.goal,
        )
        state.add_interaction_record(form_request, form_response)

        if form_response.skipped:
            content = "User cancelled the form."
        else:
            content = json.dumps({
                "goal": form_request.goal,
                "answers": form_response.answers,
            })

        if self.emitter:
            self.emitter.emit({
                "type": "status_update",
                "label": "Form completed",
                "status": "done",
            })

        return {
            "type": "tool_call",
            "tool": "show_collaborative_form",
            "success": True,
            "output": content,
            "error": None,
            "metadata": {},
        }

    def _observe(self, action_result: dict[str, Any]) -> str:
        """Generate observation from action result."""
        result_type = action_result.get("type")

        if result_type == "tool_call":
            if action_result.get("success"):
                return f"Tool '{action_result.get('tool')}' executed successfully:\n{action_result.get('output', '')}"
            else:
                return f"Tool '{action_result.get('tool')}' failed: {action_result.get('error', 'Unknown error')}"

        elif result_type == "respond":
            return action_result.get("content", "")

        elif result_type == "sub_agent_call":
            if action_result.get("success"):
                summary = action_result.get("summary", "")
                confidence = action_result.get("confidence", 0.0)
                return f"Sub-agent '{action_result.get('agent')}' completed successfully (confidence: {confidence:.2f}):\n{summary}"
            else:
                error = action_result.get("error", "Unknown error")
                return f"Sub-agent '{action_result.get('agent')}' failed: {error}"

        else:
            return f"Unknown action result type: {result_type}"
