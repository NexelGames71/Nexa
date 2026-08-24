"""Provider registry: resolve logical models to providers.

Adding a new provider means implementing AIProvider and registering it here.
No Nexcoder-facing code changes required.
"""

from __future__ import annotations

from nexa.config import Settings
from nexa.errors import MODEL_UNAVAILABLE, NexaError
from nexa.providers.base import AIProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> AIProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise NexaError("INTERNAL_ERROR", f"Unknown provider '{name}'")
        return provider

    def names(self) -> list[str]:
        return sorted(self._providers)


def build_default_registry(settings: Settings, nvidia_provider: AIProvider) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(nvidia_provider)
    return registry


def resolve_route(settings: Settings, logical_model: str) -> tuple[str, str]:
    """Map a logical model to (provider_name, provider_model).

    Raises MODEL_UNAVAILABLE for unknown logical models so clients get a
    stable error instead of an upstream 404.
    """
    provider_model = settings.resolve_provider_model(logical_model)
    if provider_model is None:
        raise NexaError(MODEL_UNAVAILABLE, "Invalid model identifier")
    return "nvidia", provider_model
