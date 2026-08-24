"""NVIDIA provider tests: success, streaming, provider error, timeout,
malformed response — using respx-style mocking via httpx MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from nexa.config import Settings
from nexa.errors import (
    MODEL_UNAVAILABLE,
    PROVIDER_RATE_LIMIT,
    PROVIDER_UNAVAILABLE,
    REQUEST_TIMEOUT,
)
from nexa.providers.base import ChatRequest
from nexa.providers.nvidia import NVIDIAProvider


_ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


def provider_with(handler) -> NVIDIAProvider:
    settings = Settings(
        nvidia_api_key="test-key",
        nvidia_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_default_model="meta/llama-3.1-70b-instruct",
    )
    provider = NVIDIAProvider(settings)
    original_client = _ORIGINAL_ASYNC_CLIENT

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(**kwargs)

    httpx.AsyncClient = factory
    return provider


@pytest.fixture()
def restore_httpx():
    yield
    httpx.AsyncClient = _ORIGINAL_ASYNC_CLIENT


def sse_body(chunks: list[dict]) -> str:
    lines = [f"data: {json.dumps(c)}" for c in chunks]
    return "\n".join(lines) + "\n\ndata: [DONE]\n\n"


class TestChat:
    async def test_successful_request(self, restore_httpx):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer test-key"
            return httpx.Response(200, json={
                "model": "meta/llama-3.1-70b-instruct",
                "choices": [{"message": {"content": "hello"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            })

        provider = provider_with(handler)
        response = await provider.chat(ChatRequest(model="m", messages=[{"role": "user", "content": "x"}]))
        assert response.content == "hello"
        assert response.usage.total_tokens == 7

    async def test_provider_error_normalized(self, restore_httpx):
        provider = provider_with(lambda req: httpx.Response(503, text="upstream boom"))
        from nexa.errors import ProviderError

        with pytest.raises(ProviderError) as exc_info:
            await provider.chat(ChatRequest(model="m", messages=[]))
        assert exc_info.value.code == PROVIDER_UNAVAILABLE
        # Raw upstream body must not leak into the message.
        assert "upstream boom" not in exc_info.value.message

    async def test_rate_limit_normalized(self, restore_httpx):
        provider = provider_with(lambda req: httpx.Response(429))
        with pytest.raises(Exception) as exc_info:
            await provider.chat(ChatRequest(model="m", messages=[]))
        assert exc_info.value.code == PROVIDER_RATE_LIMIT

    async def test_model_not_found(self, restore_httpx):
        provider = provider_with(lambda req: httpx.Response(404, text="no model"))
        with pytest.raises(Exception) as exc_info:
            await provider.chat(ChatRequest(model="m", messages=[]))
        assert exc_info.value.code == MODEL_UNAVAILABLE

    async def test_timeout(self, restore_httpx):
        def handler(request):
            raise httpx.ReadTimeout("timed out")

        provider = provider_with(handler)
        with pytest.raises(Exception) as exc_info:
            await provider.chat(ChatRequest(model="m", messages=[]))
        assert exc_info.value.code == REQUEST_TIMEOUT


class TestStream:
    async def test_stream_parses_chunks(self, restore_httpx):
        chunks = [
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"finish_reason": "stop"}],
             "usage": {"prompt_tokens": 2, "completion_tokens": 2}},
        ]

        def handler(request):
            return httpx.Response(200, content=sse_body(chunks), headers={
                "content-type": "text/event-stream"})

        provider = provider_with(handler)
        received = []
        async for chunk in provider.stream(ChatRequest(model="m", messages=[], stream=True)):
            received.append(chunk)
        assert len(received) == 3
        assert received[-1]["usage"]["completion_tokens"] == 2

    async def test_malformed_chunks_skipped(self, restore_httpx):
        raw = (
            'data: {not-json}\n'
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n'
            'data: [DONE]\n\n'
        )

        def handler(request):
            return httpx.Response(200, content=raw)

        provider = provider_with(handler)
        received = []
        async for chunk in provider.stream(ChatRequest(model="m", messages=[], stream=True)):
            received.append(chunk)
        assert len(received) == 1
        assert received[0]["choices"][0]["delta"]["content"] == "ok"

    async def test_stream_error_normalized(self, restore_httpx):
        def handler(request):
            return httpx.Response(500, text="err")

        provider = provider_with(handler)
        with pytest.raises(Exception) as exc_info:
            async for _ in provider.stream(ChatRequest(model="m", messages=[], stream=True)):
                pass
        assert exc_info.value.code == PROVIDER_UNAVAILABLE


class TestHealth:
    async def test_health_ok(self, restore_httpx):
        provider = provider_with(lambda req: httpx.Response(200, json={"data": []}))
        assert await provider.health() is True

    async def test_health_down(self, restore_httpx):
        def handler(req):
            raise httpx.ConnectError("nope")

        provider = provider_with(handler)
        assert await provider.health() is False
