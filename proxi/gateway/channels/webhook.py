"""Generic inbound webhook adapter.

Each webhook source gets a URL at ``/channels/webhook/{source_id}`` and an
HMAC secret for request verification. The ``prompt_template`` field supports
Jinja2-style ``{{key}}`` interpolation over the JSON payload.
"""

from __future__ import annotations

import re

from proxi.gateway.config import SourceConfig
from proxi.gateway.events import GatewayEvent


def render_prompt_template(template: str, data: dict) -> str:
    """Substitute ``{{dotted.path}}`` placeholders with values from *data*.

    Nested keys are resolved via dot notation (e.g. ``{{repository.name}}``).
    Missing keys are replaced with the literal placeholder string.
    """

    def _resolve(match: re.Match[str]) -> str:
        key_path = match.group(1).strip()
        value: object = data
        for part in key_path.split("."):
            if isinstance(value, dict):
                value = value.get(part, match.group(0))
            else:
                return match.group(0)
        return str(value)

    return re.sub(r"\{\{(.+?)\}\}", _resolve, template)


def build_webhook_event(source: SourceConfig, raw: dict) -> GatewayEvent:
    text = render_prompt_template(source.prompt_template, raw) if source.prompt_template else str(raw)
    return GatewayEvent(
        source_id=source.source_id,
        source_type="webhook",
        payload={"text": text, "raw": raw},
        priority=source.priority,
    )
