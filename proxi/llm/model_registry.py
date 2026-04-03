"""Model context window registry and token budget helpers."""

from __future__ import annotations

# Context windows in tokens for known models.
# Sources: Anthropic and OpenAI official documentation.
_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic Claude 3.x
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-sonnet-20240620": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # Anthropic Claude 4.x
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    # OpenAI GPT-4o family
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4o-2024-11-20": 128_000,
    "gpt-4o-2024-08-06": 128_000,
    "gpt-4o-mini-2024-07-18": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    # OpenAI GPT-5 family
    "gpt-5": 128_000,
    "gpt-5-mini": 400_000,
    "gpt-5-mini-2025-08-07": 400_000,
    "gpt-5.4-mini": 100_000_000,
    # OpenAI o-series
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
}

# Default models per provider (must match defaults in AnthropicClient / OpenAIClient).
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-5-mini-2025-08-07",
}

# Reserve 15% of the context window for output tokens.
#
# Keep compaction trigger lower than this value so compaction happens before
# we approach the hard input budget.
INPUT_BUDGET_FRACTION = 0.90
DEFAULT_COMPACTION_THRESHOLD = 0.85


def get_context_window(model: str) -> int:
    """Return the context window (in tokens) for *model*.

    Falls back to a conservative 128k for unknown models.
    """
    if model in _CONTEXT_WINDOWS:
        return _CONTEXT_WINDOWS[model]
    model_lower = model.lower()
    for key, size in _CONTEXT_WINDOWS.items():
        if model_lower.startswith(key) or key.startswith(model_lower):
            return size
    return 128_000


def token_budget_for_model(model: str) -> int:
    """Return the recommended input token budget (85% of context window)."""
    return int(get_context_window(model) * INPUT_BUDGET_FRACTION)


def _provider_for_model(model: str) -> str:
    """Classify a model id into a provider key used by gateway config."""
    model_lower = model.lower()
    if model_lower.startswith("claude"):
        return "anthropic"
    return "openai"


def get_supported_models_by_provider() -> dict[str, list[str]]:
    """Return registry model ids grouped by provider."""
    grouped: dict[str, list[str]] = {"openai": [], "anthropic": []}
    for model in sorted(_CONTEXT_WINDOWS.keys()):
        grouped[_provider_for_model(model)].append(model)
    return grouped


def get_model_limits_by_provider() -> dict[str, list[dict[str, int | str]]]:
    """Return model metadata grouped by provider with context and budget limits."""
    grouped: dict[str, list[dict[str, int | str]]] = {
        "openai": [], "anthropic": []}
    for model in sorted(_CONTEXT_WINDOWS.keys()):
        grouped[_provider_for_model(model)].append(
            {
                "model": model,
                "context_window": get_context_window(model),
                "token_budget": token_budget_for_model(model),
            }
        )
    return grouped
