"""OpenRouter provider — OpenAI-compatible aggregator.

Currently exposes exactly one model (stealth/ox-alpha). Inherits the
OpenAI-compatible wire protocol from NVIDIAProvider; only the endpoint,
credential and branding differ. Adds the optional attribution headers
OpenRouter recommends.
"""

from __future__ import annotations

from nexa.config import Settings
from nexa.providers.nvidia import NVIDIAProvider


class OpenRouterProvider(NVIDIAProvider):
    name = "openrouter"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._base_url = "https://openrouter.ai/api/v1"
        self._api_key = settings.openrouter_api_key

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        # Optional OpenRouter attribution; harmless if empty.
        if self._settings.openrouter_app_url:
            headers["HTTP-Referer"] = self._settings.openrouter_app_url
        if self._settings.openrouter_app_name:
            headers["X-Title"] = self._settings.openrouter_app_name
        return headers
