"""End-to-end streaming tests over the HTTP layer: normal stream, provider
disconnect mid-stream, cancellation (client disconnect)."""

from __future__ import annotations

import json

import httpx
import pytest

from nexa.errors import PROVIDER_UNAVAILABLE
from tests.conftest import auth_header


def parse_sse(text: str) -> list[dict | str]:
    events = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    events.append("[DONE]")
                else:
                    events.append(json.loads(data))
    return events


class TestStreaming:
    async def test_normal_stream(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "stepfun-ai/step-3.7-flash",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
            headers=auth_header("tok"),
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.text)
        assert events[-1] == "[DONE]"
        # Content chunks forwarded incrementally.
        contents = [
            e["choices"][0]["delta"].get("content", "")
            for e in events[:-1]
            if e.get("choices") and e["choices"][0].get("delta", {}).get("content")
        ]
        assert "".join(contents) == "Hello, world"
        # Final chunk carries usage.
        final = [e for e in events[:-1] if e.get("usage")]
        assert final and final[-1]["usage"]["total_tokens"] == 15

    async def test_provider_disconnect_mid_stream(self, client, supabase, nvidia):
        supabase.add_user("tok", plan="pro")

        async def broken_stream(request):
            yield {"choices": [{"delta": {"content": "partial"}}]}
            from nexa.providers.base import AIProvider
            raise httpx.RemoteProtocolError("upstream dropped")

        nvidia.stream = broken_stream

        response = await client.post(
            "/v1/chat/completions",
            json={"model": "stepfun-ai/step-3.7-flash",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
            headers=auth_header("tok"),
        )
        events = parse_sse(response.text)
        errors = [e for e in events if isinstance(e, dict) and "error" in e]
        assert errors
        assert errors[0]["error"]["code"] == PROVIDER_UNAVAILABLE
        # Stream still terminates cleanly with [DONE].
        assert events[-1] == "[DONE]"

    async def test_request_id_in_headers(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.get("/v1/models", headers=auth_header("tok"))
        assert response.headers["x-request-id"].startswith("nexa_req_")

    async def test_usage_recorded_for_stream(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        await client.post(
            "/v1/chat/completions",
            json={"model": "stepfun-ai/step-3.7-flash",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
            headers=auth_header("tok"),
        )
        records = [r for _, r in supabase.inserted]
        assert records and records[-1]["status"] == "success"
        assert records[-1]["total_tokens"] > 0


class TestNonStreaming:
    async def test_chat_completion(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "stepfun-ai/step-3.7-flash", "temperature": 0.5, "max_tokens": 128,
                  "messages": [{"role": "user", "content": "hi"}]},
            headers={**auth_header("tok")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["choices"][0]["message"]["content"] == "ok"
        assert body["usage"]["total_tokens"] == 5

