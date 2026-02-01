"""Summarizer sub-agent for condensing information."""

from proxi.agents.base import AgentContext, BaseSubAgent, SubAgentResult
from proxi.core.state import Message
from proxi.llm.base import LLMClient
from proxi.observability.logging import get_logger

logger = get_logger(__name__)


class SummarizerAgent(BaseSubAgent):
    """Sub-agent that summarizes text or conversation history."""

    def __init__(self, llm_client: LLMClient):
        """Initialize the summarizer agent."""
        super().__init__(
            name="summarizer",
            description="Summarizes text, conversations, or documents into concise summaries",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text or content to summarize",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum length of summary in words",
                        "default": 100,
                    },
                },
                "required": ["text"],
            },
            system_prompt="You are a helpful assistant that creates concise, accurate summaries. Focus on key points and main ideas.",
        )
        self.llm_client = llm_client
        self.logger = logger

    async def run(
        self,
        context: AgentContext,
        max_turns: int = 10,
        max_tokens: int = 2000,
        max_time: float = 30.0,
    ) -> SubAgentResult:
        """Run the summarizer agent."""
        # Extract text from context
        # The task field contains what to summarize
        text = context.task
        
        # Check context_refs for additional parameters
        max_length = 100
        if isinstance(context.context_refs, dict):
            # If context_refs is a dict, extract values
            text = context.context_refs.get("text", text)
            max_length = context.context_refs.get("max_length", 100)
        elif isinstance(context.context_refs, list):
            # If it's a list, the task should contain the text
            pass

        if not text:
            return SubAgentResult(
                summary="No text provided to summarize",
                artifacts={},
                confidence=0.0,
                success=False,
                error="No text provided",
            )

        try:
            # Create messages for summarization
            messages = [
                Message(
                    role="system",
                    content=self.system_prompt,
                ),
                Message(
                    role="user",
                    content=f"Please summarize the following text in approximately {max_length} words:\n\n{text}",
                ),
            ]

            # Call LLM
            response = await self.llm_client.generate(messages=messages)
            summary = response.decision.payload.get("content", "")

            if not summary:
                return SubAgentResult(
                    summary="Failed to generate summary",
                    artifacts={},
                    confidence=0.0,
                    success=False,
                    error="LLM did not return a summary",
                )

            # Calculate confidence based on whether we got a response
            confidence = 0.9 if summary else 0.0

            return SubAgentResult(
                summary=summary,
                artifacts={"summary": summary, "original_length": len(text), "summary_length": len(summary)},
                confidence=confidence,
                success=True,
                error=None,
                follow_up_suggestions=[],
            )

        except Exception as e:
            self.logger.error("summarizer_error", error=str(e))
            return SubAgentResult(
                summary="Error during summarization",
                artifacts={},
                confidence=0.0,
                success=False,
                error=str(e),
            )
