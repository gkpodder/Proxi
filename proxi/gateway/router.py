"""Event routing — resolves source → agent → session."""

from __future__ import annotations

from proxi.gateway.config import GatewayConfig
from proxi.gateway.events import GatewayEvent


class RoutingError(RuntimeError):
    pass


class EventRouter:
    """Pure lookup: two config reads, one ``session_id`` out."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    def resolve(self, event: GatewayEvent) -> str:
        """Stamp and return ``session_id`` for *event*.

        The returned value is always ``"{agent_id}/{session_name}"``.
        Raises ``RoutingError`` if the source or agent is unknown.
        """
        source = self._config.sources.get(event.source_id)
        if source is None:
            raise RoutingError(f"No source config for {event.source_id!r}")

        agent = self._config.agents.get(source.target_agent)
        if agent is None:
            raise RoutingError(
                f"Source {event.source_id!r} targets unknown agent {source.target_agent!r}"
            )

        session_name = source.target_session or agent.default_session
        return f"{agent.agent_id}/{session_name}"

    def resolve_default(self) -> str:
        """Return the session_id for the first configured agent's default session.

        Used by the HTTP direct-invocation endpoint when no session is specified.
        """
        if not self._config.agents:
            raise RoutingError("No agents configured")
        agent = next(iter(self._config.agents.values()))
        return f"{agent.agent_id}/{agent.default_session}"
