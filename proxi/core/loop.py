"""Main agent loop implementation."""

import json
import os
import asyncio
import time
from typing import Any, Protocol

from proxi.agents.registry import SubAgentManager
from proxi.core.compactor import ContextCompactor
from proxi.core.planner import Planner
from proxi.core.reflection import Reflector
from proxi.core.state import AgentState, AgentStatus, Message, TurnState, TurnStatus, WorkspaceConfig
from proxi.llm.base import LLMClient
from proxi.llm.schemas import DecisionType, ModelDecision, ToolCall
from proxi.observability.logging import get_logger
from proxi.observability.perf import elapsed_ms, emit_perf, now_ns
from proxi.observability.tracing import TraceContext
from proxi.tools.registry import ToolRegistry

logger = get_logger(__name__)

# Tools that are blocked while plan_mode is active.
# manage_plan is intentionally omitted — that's how the agent writes the plan.
_PLAN_MODE_WRITE_BLOCKED_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "edit_file",
    "apply_patch",
    "execute_code",
    "shell",
    "manage_todos",
})


def _is_context_length_error(exc: Exception) -> bool:
    """Return True if the exception looks like a context-window overflow."""
    msg = str(exc).lower()
    return any(x in msg for x in [
        "context_length_exceeded",
        "context window",
        "maximum context length",
        "too many tokens",
        "413",
    ])


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
        compactor: ContextCompactor | None = None,
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
        self.compactor = compactor

    async def run(self, initial_message: str, reasoning_effort: str = "minimal") -> AgentState:
        """
        Run the agent loop with an initial message.

        Args:
            initial_message: Initial user message
            reasoning_effort: LLM reasoning effort for this run ("minimal", "low", "medium", "high")

        Returns:
            Final agent state
        """
        state = AgentState(
            status=AgentStatus.RUNNING,
            max_turns=self.max_turns,
            start_time=time.time(),
            workspace=self.workspace,
            reasoning_effort=reasoning_effort,
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
        if state.workspace is None and self.workspace is not None:
            state.workspace = self.workspace
        # Loaded / legacy state may omit max_turns (Pydantic default); loop config is authoritative.
        state.max_turns = self.max_turns
        state.add_message(Message(role="user", content=user_message))
        state.status = AgentStatus.RUNNING
        if state.end_time is not None:
            state.end_time = None
        self.logger.info("agent_loop_continue", message=user_message[:100])
        return await self._run_loop(state)

    async def _run_loop(self, state: AgentState) -> AgentState:
        """Inner loop: run until completion or failure."""
        try:
            turn_budget_ms = float(os.getenv("PROXI_BUDGET_TURN_MS", "30000"))
            decide_budget_ms = float(
                os.getenv("PROXI_BUDGET_DECIDE_MS", "20000"))
            act_budget_ms = float(os.getenv("PROXI_BUDGET_ACT_MS", "15000"))
            with TraceContext("agent_loop"):
                while state.can_continue():
                    turn_start_ns = now_ns()
                    decide_ms = 0.0
                    act_ms = 0.0
                    observe_ms = 0.0
                    reflect_ms = 0.0
                    state.current_turn += 1
                    turn = TurnState(
                        turn_number=state.current_turn,
                        status=TurnStatus.PENDING,
                        start_time=time.time(),
                    )
                    state.add_turn(turn)

                    self.logger.debug("turn_start", turn=state.current_turn)

                    try:
                        # --- Pre-flight compaction check ---
                        if self.compactor is not None and self.planner.prompt_builder._cached_system_prefix:
                            self.compactor.system_prompt = self.planner.prompt_builder._cached_system_prefix
                        if self.compactor is not None:
                            current_tokens = (
                                state.turns[-2].tokens_used
                                if len(state.turns) >= 2
                                else state.total_tokens
                            )
                            compaction_threshold_tokens = int(
                                self.compactor.context_window
                                * self.compactor.compaction_threshold
                            )
                            should_show_compaction_status = (
                                current_tokens >= compaction_threshold_tokens
                            )
                            if should_show_compaction_status and self.emitter:
                                self.emitter.emit(
                                    {
                                        "type": "status_update",
                                        "label": "Compacting",
                                        "status": "running",
                                        "tui_abortable": False,
                                    }
                                )
                            compact_result = await self.compactor.maybe_compact(
                                state, current_tokens=current_tokens
                            )
                            if compact_result.compaction_triggered:
                                self.logger.info(
                                    "context_compacted",
                                    turn=state.current_turn,
                                    from_tokens=compact_result.original_tokens,
                                    to_tokens=compact_result.compacted_token_estimate,
                                )
                                if should_show_compaction_status and self.emitter:
                                    self.emitter.emit(
                                        {
                                            "type": "status_update",
                                            "label": "Compacted",
                                            "status": "done",
                                            "tui_abortable": False,
                                        }
                                    )

                        # REASON → DECIDE
                        turn.status = TurnStatus.DECIDING
                        decide_start_ns = now_ns()
                        if self.emitter:
                            self.emitter.emit(
                                {
                                    "type": "status_update",
                                    "label": "Thinking...",
                                    "status": "running",
                                }
                            )
                        decision, usage = await self._decide(
                            state, emit_stream=self.emitter is not None,
                            reasoning_effort=state.reasoning_effort,
                        )
                        if self.emitter:
                            self.emitter.emit(
                                {
                                    "type": "status_update",
                                    "label": "Thinking...",
                                    "status": "done",
                                }
                            )
                        decide_ms = elapsed_ms(decide_start_ns)

                        # Token accounting:
                        # - total_tokens tracks spend (input + output)
                        # - turn.tokens_used tracks current context size (input/prompt only)
                        state.total_tokens += usage.get("total_tokens", 0)
                        turn.tokens_used = usage.get(
                            "prompt_tokens",
                            usage.get("input_tokens", usage.get("total_tokens", 0)),
                        )

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

                                # Execute all tool calls, optionally in parallel for safe tools.
                                parsed_calls: list[tuple[str,
                                                         str, dict[str, Any]]] = []
                                for tool_call in tool_calls:
                                    tool_call_id = tool_call.get("id", "")
                                    tool_name = tool_call.get(
                                        "function", {}).get("name", "")
                                    tool_args_str = tool_call.get(
                                        "function", {}).get("arguments", "{}")
                                    try:
                                        tool_args = json.loads(tool_args_str) if isinstance(
                                            tool_args_str, str) else tool_args_str
                                    except json.JSONDecodeError:
                                        tool_args = {}
                                    parsed_calls.append(
                                        (tool_call_id, tool_name, tool_args))

                                # Default 16: read/grep/glob batches often exceed 4 paths; higher
                                # concurrency cuts wall-clock time. Tune down via PROXI_TOOL_PARALLELISM.
                                parallel_limit = max(
                                    1, int(os.getenv("PROXI_TOOL_PARALLELISM", "16")))

                                async def exec_one(
                                    tool_call_id: str, tool_name: str, tool_args: dict[str, Any]
                                ) -> dict[str, Any]:
                                    temp_decision = ModelDecision.tool_call(
                                        ToolCall(
                                            id=tool_call_id,
                                            name=tool_name,
                                            arguments=tool_args,
                                        ),
                                        reasoning=None,
                                    )
                                    tool_start_ns = now_ns()
                                    result = await self._act(state, temp_decision, turn)
                                    # Merge outer elapsed_ms into the result dict so
                                    # _observe() can report timing even for parallel runs.
                                    outer_ms = elapsed_ms(tool_start_ns)
                                    result["metadata"] = {
                                        **(result.get("metadata") or {}),
                                        "elapsed_ms": outer_ms,
                                    }
                                    return {
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                        "result": result,
                                        "elapsed_ms": outer_ms,
                                    }

                                # Partition into safe (parallelisable) and unsafe (sequential).
                                # Pass args so call_tool delegation can check the inner tool.
                                safe_indices = [
                                    i for i, (_, name, args) in enumerate(parsed_calls)
                                    if self.tool_registry.is_parallel_safe(name, args)
                                ]
                                unsafe_indices = [
                                    i for i, (_, name, args) in enumerate(parsed_calls)
                                    if not self.tool_registry.is_parallel_safe(name, args)
                                ]

                                results_by_index: dict[int, dict[str, Any]] = {}

                                if parallel_limit > 1 and safe_indices:
                                    semaphore = asyncio.Semaphore(parallel_limit)

                                    async def run_with_limit(
                                        idx: int, tool_call_id: str, tool_name: str, tool_args: dict[str, Any]
                                    ) -> tuple[int, dict[str, Any]]:
                                        async with semaphore:
                                            return idx, await exec_one(tool_call_id, tool_name, tool_args)

                                    safe_tasks = [
                                        asyncio.create_task(run_with_limit(
                                            i, *parsed_calls[i]))
                                        for i in safe_indices
                                    ]
                                    # Timeout: max individual tool timeout + 5 s buffer.
                                    gather_timeout = max(
                                        (getattr(self.tool_registry.get(parsed_calls[i][1]), "_timeout", 30)
                                         for i in safe_indices),
                                        default=30,
                                    ) + 5.0
                                    try:
                                        gathered = await asyncio.wait_for(
                                            asyncio.gather(*safe_tasks, return_exceptions=True),
                                            timeout=gather_timeout,
                                        )
                                    except asyncio.TimeoutError:
                                        gathered = []
                                        for t in safe_tasks:
                                            t.cancel()
                                    for item in gathered:
                                        if isinstance(item, Exception):
                                            continue
                                        idx, r = item
                                        results_by_index[idx] = r
                                else:
                                    for i in safe_indices:
                                        results_by_index[i] = await exec_one(*parsed_calls[i])

                                for i in unsafe_indices:
                                    results_by_index[i] = await exec_one(*parsed_calls[i])

                                action_results = [results_by_index[i] for i in range(len(parsed_calls))]

                                act_ms += sum(float(r.get("elapsed_ms", 0.0))
                                              for r in action_results)

                                # Add all tool response messages
                                observe_start_ns = now_ns()
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
                                observe_ms += elapsed_ms(observe_start_ns)
                            else:
                                # Single tool call - original behavior
                                state.add_message(
                                    Message(
                                        role="assistant",
                                        content=None,  # Must be None when tool_calls is present
                                        tool_calls=tool_calls,
                                    )
                                )

                                act_start_ns = now_ns()
                                action_result = await self._act(state, decision, turn)
                                act_ms += elapsed_ms(act_start_ns)

                                # OBSERVE
                                turn.status = TurnStatus.OBSERVING
                                turn.action_result = action_result
                                observe_start_ns = now_ns()
                                observation = self._observe(action_result)
                                observe_ms += elapsed_ms(observe_start_ns)
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
                            act_start_ns = now_ns()
                            action_result = await self._act(state, decision, turn)
                            act_ms += elapsed_ms(act_start_ns)

                            # OBSERVE
                            turn.status = TurnStatus.OBSERVING
                            turn.action_result = action_result
                            observe_start_ns = now_ns()
                            observation = self._observe(action_result)
                            observe_ms += elapsed_ms(observe_start_ns)
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
                        reflect_start_ns = now_ns()
                        reflection = await self.reflector.reflect(state, turn)
                        reflect_ms = elapsed_ms(reflect_start_ns)
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

                    except asyncio.CancelledError:
                        turn.status = TurnStatus.ERROR
                        turn.error = "Turn cancelled"
                        raise
                    except Exception as e:
                        turn.status = TurnStatus.ERROR
                        turn.error = str(e)
                        self.logger.error(
                            "turn_error", turn=state.current_turn, error=str(e))

                        # If the exception happened during a tool call, the
                        # assistant message with tool_calls was already committed
                        # to history but the tool result(s) were not.  Inject
                        # synthetic error results so the next LLM call receives a
                        # valid conversation (OpenAI 400s if any function_call
                        # lacks a matching tool message).
                        try:
                            if decision.type == DecisionType.TOOL_CALL:
                                answered = {
                                    m.tool_call_id
                                    for m in state.history
                                    if m.role == "tool" and m.tool_call_id
                                }
                                for msg in reversed(state.history):
                                    if msg.role == "assistant" and msg.tool_calls:
                                        for tc in msg.tool_calls:
                                            tc_id = (
                                                tc.get("id", "")
                                                if isinstance(tc, dict)
                                                else getattr(tc, "id", "")
                                            )
                                            tc_name = (
                                                tc.get("function", {}).get("name", "")
                                                if isinstance(tc, dict)
                                                else getattr(tc, "name", "")
                                            )
                                            if tc_id and tc_id not in answered:
                                                state.add_message(Message(
                                                    role="tool",
                                                    content=f"[Tool error: {e}]",
                                                    name=tc_name,
                                                    tool_call_id=tc_id,
                                                ))
                                        break
                        except Exception:
                            pass  # never let recovery logic crash the loop

                        # Reactive compaction: if the error is a context-length
                        # overflow, compact and retry the turn instead of failing.
                        if self.compactor is not None and _is_context_length_error(e):
                            try:
                                compact_result = await self.compactor.force_compact(
                                    state,
                                    current_tokens=self.compactor.context_window,
                                )
                                if compact_result.compaction_triggered:
                                    self.logger.info(
                                        "reactive_compaction",
                                        turn=state.current_turn,
                                        from_tokens=compact_result.original_tokens,
                                    )
                                    turn.status = TurnStatus.PENDING
                                    turn.error = None
                                    continue  # retry this turn
                            except Exception as compact_err:
                                self.logger.error(
                                    "reactive_compaction_failed", error=str(compact_err)
                                )

                        if not self.reflector.should_retry(state, turn):
                            state.status = AgentStatus.FAILED
                            break

                    finally:
                        turn.end_time = time.time()
                        turn_total_ms = elapsed_ms(turn_start_ns)
                        emit_perf(
                            "perf_turn",
                            turn=turn.turn_number,
                            status=turn.status.value,
                            decision_type=(
                                turn.decision.get("type")
                                if isinstance(turn.decision, dict)
                                else None
                            ),
                            total_ms=round(turn_total_ms, 3),
                            decide_ms=round(decide_ms, 3),
                            act_ms=round(act_ms, 3),
                            observe_ms=round(observe_ms, 3),
                            reflect_ms=round(reflect_ms, 3),
                            history_len=len(state.history),
                        )
                        if turn_total_ms > turn_budget_ms:
                            emit_perf(
                                "perf_budget_exceeded",
                                component="agent_loop",
                                budget="turn_total_ms",
                                value_ms=round(turn_total_ms, 3),
                                threshold_ms=turn_budget_ms,
                            )
                        if decide_ms > decide_budget_ms:
                            emit_perf(
                                "perf_budget_exceeded",
                                component="agent_loop",
                                budget="decide_ms",
                                value_ms=round(decide_ms, 3),
                                threshold_ms=decide_budget_ms,
                            )
                        if act_ms > act_budget_ms:
                            emit_perf(
                                "perf_budget_exceeded",
                                component="agent_loop",
                                budget="act_ms",
                                value_ms=round(act_ms, 3),
                                threshold_ms=act_budget_ms,
                            )

        except asyncio.CancelledError:
            state.status = AgentStatus.CANCELLED
            self.logger.info("agent_loop_cancelled")
            raise
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
        self, state: AgentState, *, emit_stream: bool = False, reasoning_effort: str = "minimal",
    ) -> tuple[ModelDecision, dict[str, int]]:
        """Make a decision based on current state."""
        tools = self.tool_registry.to_specs()
        deferred_count = self.tool_registry.deferred_tool_count()
        deferred_specs = self.tool_registry.get_deferred_specs() if deferred_count > 0 else []
        agents = None
        if self.sub_agent_manager:
            agents = self.sub_agent_manager.registry.to_specs()

        async def stream_callback(chunk: str) -> None:
            if self.emitter:
                self.emitter.emit({"type": "text_stream", "content": chunk})

        stream_cb = stream_callback if emit_stream else None
        decision, usage = await self.planner.decide(
            state, tools, agents, stream_callback=stream_cb,
            deferred_tool_count=deferred_count, deferred_specs=deferred_specs,
            reasoning_effort=reasoning_effort,
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

            # Intercept ask_user_question — never execute via registry
            if tool_name == "ask_user_question":
                return await self._handle_ask_user_question(
                    state, tool_call_id, arguments, turn
                )

            # Block write tools in plan mode (cache-safe: schemas unchanged, blocked at runtime).
            # Two conditions: hardcoded frozenset (backward compat) OR read_only=False on the
            # tool object (auto-blocks new write tools without frozenset edits).
            # manage_plan is explicitly allowed even though it has read_only=False.
            if state.plan_mode:
                tool_obj = self.tool_registry.get(tool_name)
                blocked_by_flag = (
                    getattr(tool_obj, "read_only", True) is False
                    and tool_name != "manage_plan"
                )
                blocked_by_name = tool_name in _PLAN_MODE_WRITE_BLOCKED_TOOLS
                plan_mode_blocked = blocked_by_flag or blocked_by_name
            else:
                plan_mode_blocked = False
            if plan_mode_blocked:
                if self.emitter:
                    self.emitter.emit({
                        "type": "tool_start",
                        "tool": tool_name,
                        "arguments": arguments,
                    })
                    self.emitter.emit({
                        "type": "tool_done",
                        "tool": tool_name,
                        "success": False,
                        "error": "Plan mode: write operations are not allowed during planning. "
                                 "Use manage_plan to write the plan, then the user can accept it.",
                    })
                return {
                    "type": "tool_call",
                    "tool": tool_name,
                    "success": False,
                    "output": "",
                    "error": "Plan mode: write operations are not allowed during planning. "
                             "Use manage_plan to write the plan, then the user can accept it.",
                    "metadata": {},
                }

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

            tool_exec_start_ns = now_ns()
            result = await self.tool_registry.execute(tool_name, arguments)
            tool_exec_ms = elapsed_ms(tool_exec_start_ns)
            emit_perf(
                "perf_tool_exec",
                turn=turn.turn_number,
                tool=tool_name,
                success=result.success,
                elapsed_ms=round(tool_exec_ms, 3),
            )

            if self.emitter:
                if result.output:
                    log_line = self._tool_log_summary(tool_name, arguments, result.output)
                    if log_line:
                        self.emitter.emit({
                            "type": "tool_log",
                            "content": log_line,
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

            subagent_start_ns = now_ns()
            result = await self.sub_agent_manager.run(
                agent_name=agent_name,
                context=context,
                max_turns=10,  # Default budgets for sub-agents
                max_tokens=2000,
                max_time=30.0,
            )
            emit_perf(
                "perf_subagent_exec",
                turn=turn.turn_number,
                agent=agent_name,
                success=result.success,
                elapsed_ms=round(elapsed_ms(subagent_start_ns), 3),
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

    @staticmethod
    def _tool_log_summary(tool_name: str, arguments: dict[str, Any], output: str) -> str | None:
        """Return a concise one-line TUI summary for a tool result."""
        if tool_name == "call_tool":
            target = arguments.get("tool_name", "?") if isinstance(arguments, dict) else "?"
            first = output.strip().split("\n")[0].strip()
            return f"{target} → {first[:80]}" if first else f"{target} → done"
        first_line = output.strip().split("\n")[0].strip()
        return first_line[:100] if first_line else None

    async def _handle_ask_user_question(
        self,
        state: AgentState,
        tool_call_id: str,
        arguments: dict[str, Any] | str,
        turn: TurnState,
    ) -> dict[str, Any]:
        """Intercept ask_user_question: validate, emit to TUI, await response."""
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
                "tool": "ask_user_question",
                "success": False,
                "output": "",
                "error": f"Schema validation error — fix and retry:\n{e}",
                "metadata": {},
            }
        if self.form_bridge is None:
            return {
                "type": "tool_call",
                "tool": "ask_user_question",
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
            "tool": "ask_user_question",
            "success": True,
            "output": content,
            "error": None,
            "metadata": {},
        }

    def _observe(self, action_result: dict[str, Any]) -> str:
        """Generate observation from action result."""
        result_type = action_result.get("type")

        if result_type == "tool_call":
            elapsed_ms = (action_result.get("metadata") or {}).get("elapsed_ms", 0)
            timing = f" (took {elapsed_ms / 1000:.1f}s)" if elapsed_ms > 3000 else ""
            if action_result.get("success"):
                return f"Tool '{action_result.get('tool')}' executed successfully{timing}:\n{action_result.get('output', '')}"
            else:
                err = action_result.get('error') or action_result.get('output') or 'Unknown error'
                return f"Tool '{action_result.get('tool')}' failed{timing}: {err}"

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

