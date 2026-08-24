"""Provider registry: resolve model ids to providers.

Model ids are the real NVIDIA NIM identifiers end-to-end. Adding a new
provider means implementing AIProvider and registering it here.
"""

from __future__ import annotations

from nexa.config import Settings
from nexa.errors import MODEL_UNAVAILABLE, NexaError
from nexa.providers.base import AIProvider
from nexa.routing.catalog import known_model


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


def resolve_route(settings: Settings, model_id: str) -> tuple[str, str]:
    """Map a catalog model id to (provider_name, provider_model).

    By default the id passes through unchanged to NVIDIA. An explicit
    override may be set via NEXA_MODEL_ROUTES as `model-id=provider-model`
    pairs (useful for canary swaps without a redeploy of clients).
    Raises MODEL_UNAVAILABLE for unknown ids so clients get a stable error.
    """
    if not known_model(model_id):
        raise NexaError(MODEL_UNAVAILABLE, "Invalid model identifier")
    return "nvidia", settings.resolve_provider_model(model_id)
