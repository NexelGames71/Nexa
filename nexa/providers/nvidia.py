"""NVIDIA hosted NIM provider (OpenAI-compatible endpoint).

All NVIDIA-specific behavior is isolated here: base URL, API key header,
error mapping, SSE quirks. Nothing else in Nexa imports NVIDIA details.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from nexa.config import Settings
from nexa.errors import (
    MODEL_UNAVAILABLE,
    PROVIDER_RATE_LIMIT,
    PROVIDER_UNAVAILABLE,
    REQUEST_TIMEOUT,
    ProviderError,
    RequestTimeoutError,
)
from nexa.providers.base import AIProvider, ChatRequest, ChatResponse, ModelInfo, Usage

logger = logging.getLogger("nexa.provider.nvidia")

_STATUS_MAP: dict[int, str] = {
    401: PROVIDER_UNAVAILABLE,  # upstream auth problem: never leak, report as outage
    403: PROVIDER_UNAVAILABLE,
    404: MODEL_UNAVAILABLE,
    429: PROVIDER_RATE_LIMIT,
    500: PROVIDER_UNAVAILABLE,
    502: PROVIDER_UNAVAILABLE,
    503: PROVIDER_UNAVAILABLE,
    504: REQUEST_TIMEOUT,
}


class NVIDIAProvider(AIProvider):
    name = "nvidia"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.nvidia_base_url.rstrip("/")
        self._api_key = settings.nvidia_api_key

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._base_url)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        base = self._base_url
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}/{path.lstrip('/')}"

    def _map_status(self, status_code: int) -> ProviderError:
        code = _STATUS_MAP.get(status_code, PROVIDER_UNAVAILABLE)
        messages = {
            MODEL_UNAVAILABLE: "Requested model is not available on the provider",
            PROVIDER_RATE_LIMIT: "Provider capacity limit reached; retry shortly",
            REQUEST_TIMEOUT: "Provider request timed out",
        }
        message = messages.get(code, "AI provider is temporarily unavailable")
        error = ProviderError(code, message)
        if code == PROVIDER_RATE_LIMIT:
            error.headers = {"Retry-After": "5"}
        else:
            error.headers = {}
        return error

    def build_payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "stream": request.stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stream_options:
            payload["stream_options"] = request.stream_options
        payload.update(request.extras)
        return payload

    async def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            async with httpx.AsyncClient(timeout=self._settings.upstream_timeout_seconds) as client:
                response = await client.post(
                    self._url("chat/completions"),
                    json=self.build_payload(request),
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise RequestTimeoutError() from exc
        except httpx.HTTPError as exc:
            logger.warning("nvidia connect error: %s", type(exc).__name__)
            raise self._map_status(503) from exc

        if response.status_code >= 400:
            logger.warning(
                "nvidia upstream error status=%s", response.status_code
            )
            raise self._map_status(response.status_code)

        data = response.json()
        choices = data.get("choices") or [{}]
        usage_raw = data.get("usage") or {}
        return ChatResponse(
            content=choices[0].get("message", {}).get("content", ""),
            model=data.get("model", request.model),
            finish_reason=choices[0].get("finish_reason"),
            usage=Usage(
                input_tokens=int(usage_raw.get("prompt_tokens", 0)),
                output_tokens=int(usage_raw.get("completion_tokens", 0)),
            ),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed SSE chunk dicts from the upstream stream.

        Malformed chunks are skipped. Raises normalized errors on connect /
        HTTP failures. The caller owns client-disconnect handling.
        """
        request.stream = True
        try:
            async with httpx.AsyncClient(timeout=self._settings.upstream_timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    self._url("chat/completions"),
                    json=self.build_payload(request),
                    headers=self._headers(),
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        logger.warning(
                            "nvidia stream upstream error status=%s", response.status_code
                        )
                        raise self._map_status(response.status_code)

                    buffer = ""
                    async for text in response.aiter_text():
                        buffer += text
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            try:
                                yield json.loads(data)
                            except json.JSONDecodeError:
                                logger.debug("skipping malformed SSE chunk")
                                continue
        except httpx.TimeoutException as exc:
            raise RequestTimeoutError() from exc
        except httpx.HTTPError as exc:
            if isinstance(exc, httpx.StreamError) or isinstance(exc, httpx.RemoteProtocolError):
                logger.warning("upstream disconnect: %s", type(exc).__name__)
                raise self._map_status(502) from exc
            logger.warning("nvidia stream connect error: %s", type(exc).__name__)
            raise self._map_status(503) from exc

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._url("models"), headers=self._headers())
            if response.status_code >= 400:
                raise self._map_status(response.status_code)
            data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("nvidia list_models error: %s", type(exc).__name__)
            raise self._map_status(503) from exc
        models = []
        for item in data.get("data", []):
            models.append(ModelInfo(id=str(item.get("id", "")), owned_by="nvidia"))
        return models

    async def health(self) -> bool:
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self._url("models"), headers=self._headers())
            return response.status_code == 200
        except httpx.HTTPError:
            return False
