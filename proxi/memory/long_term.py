"""Long-term memory for persistent context."""

from typing import Any


class LongTermMemory:
    """Long-term memory for persistent context storage."""

    def __init__(self):
        """Initialize long-term memory."""
        self._storage: dict[str, Any] = {}

    def store(self, key: str, value: Any) -> None:
        """Store a value in long-term memory."""
        self._storage[key] = value

    def retrieve(self, key: str) -> Any | None:
        """Retrieve a value from long-term memory."""
        return self._storage.get(key)

    def search(self, query: str) -> list[tuple[str, Any]]:
        """Search for values matching a query (simple implementation)."""
        # Simple string matching - can be enhanced with embeddings later
        results = []
        query_lower = query.lower()
        for key, value in self._storage.items():
            if query_lower in key.lower() or (
                isinstance(value, str) and query_lower in value.lower()
            ):
                results.append((key, value))
        return results

    def clear(self) -> None:
        """Clear all stored values."""
        self._storage.clear()
