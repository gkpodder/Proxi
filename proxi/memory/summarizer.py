"""Memory summarizer for condensing conversation history."""

from proxi.core.state import Message
from proxi.memory.short_term import ShortTermMemory


class Summarizer:
    """Summarizer for condensing long conversation histories."""

    def __init__(self, max_messages: int = 50):
        """Initialize the summarizer."""
        self.max_messages = max_messages

    def summarize(self, messages: list[Message]) -> list[Message]:
        """
        Summarize messages if they exceed the threshold.

        Args:
            messages: List of messages to potentially summarize

        Returns:
            Summarized messages (or original if under threshold)
        """
        if len(messages) <= self.max_messages:
            return messages

        # Simple summarization: keep first system/user message and recent messages
        # More sophisticated summarization can be added later with LLM
        summary_messages = []

        # Keep first message if it's system or user
        if messages:
            first_msg = messages[0]
            if first_msg.role in ("system", "user"):
                summary_messages.append(first_msg)

        # Keep recent messages
        recent_count = self.max_messages - len(summary_messages)
        if recent_count > 0:
            summary_messages.extend(messages[-recent_count:])

        # Add a summary message
        summary_msg = Message(
            role="system",
            content=f"[Previous {len(messages) - len(summary_messages)} messages summarized]",
        )
        summary_messages.insert(1, summary_msg)

        return summary_messages
