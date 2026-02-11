"""Short-term memory for conversation history."""

from collections.abc import Sequence

from proxi.core.state import Message


class ShortTermMemory:
    """Short-term memory for managing conversation history."""

    def __init__(self, max_messages: int = 100):
        """Initialize short-term memory."""
        self.max_messages = max_messages
        self._messages: list[Message] = []

    def add(self, message: Message) -> None:
        """Add a message to memory."""
        self._messages.append(message)
        if len(self._messages) > self.max_messages:
            # Keep the most recent messages
            self._messages = self._messages[-self.max_messages :]

    def add_many(self, messages: Sequence[Message]) -> None:
        """Add multiple messages."""
        for message in messages:
            self.add(message)

    def get_all(self) -> list[Message]:
        """Get all messages."""
        return self._messages.copy()

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()

    def get_recent(self, count: int) -> list[Message]:
        """Get the most recent messages."""
        return self._messages[-count:] if count > 0 else []
