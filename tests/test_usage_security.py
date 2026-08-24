"""Usage tracking + security tests."""

from __future__ import annotations

import json

from tests.conftest import VALID_CHAT_BODY, auth_header


class TestUsage:
    async def test_success_recorded(self, client, supabase):
        supabase.add_user("tok", user_id="u-9", plan="pro")
        await client.post("/v1/chat/completions", json=VALID_CHAT_BODY,
                          headers=auth_header("tok"))
        records = [r for _, r in supabase.inserted]
        assert len(records) == 1
        record = records[0]
        assert record["status"] == "success"
        assert record["user_id"] == "u-9"
        assert record["model"] == "nexa-general"
        assert record["provider"] == "nvidia"
        assert record["total_tokens"] > 0
        assert record["request_id"].startswith("nexa_req_")

    async def test_failure_recorded(self, client, supabase, nvidia):
        supabase.add_user("tok", plan="pro")
        nvidia.fail_with = RuntimeError("boom")
        await client.post(
            "/v1/chat/completions",
            json={"model": "nexa-general",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
            headers=auth_header("tok"),
        )
        records = [r for _, r in supabase.inserted]
        assert records and records[-1]["status"] == "error"

    async def test_no_prompt_content_stored(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        secret = "TOPSECRET-CONTENT-1234"
        await client.post(
            "/v1/chat/completions",
            json={"model": "nexa-general",
                  "messages": [{"role": "user", "content": secret}]},
            headers=auth_header("tok"),
        )
        for _, record in supabase.inserted:
            assert secret not in json.dumps(record)


class TestSecurity:
    async def test_nvidia_key_never_returned(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post("/v1/chat/completions", json=VALID_CHAT_BODY,
                                     headers=auth_header("tok"))
        assert "nvapi" not in response.text.lower()
        response = await client.get("/v1/models", headers=auth_header("tok"))
        assert "nvapi" not in response.text.lower()
        response = await client.get("/v1/health")
        assert "nvapi" not in response.text.lower()

    async def test_health_has_no_secrets(self, client):
        response = await client.get("/v1/health")
        assert response.status_code == 200
        body = response.text.lower()
        for marker in ("key", "secret", "password", "nvapi"):
            assert marker not in body.replace("_key\":", "")

    async def test_error_responses_are_structured(self, client):
        response = await client.post(
            "/v1/chat/completions",
            json={"model": 123, "messages": "nope"},
            headers=auth_header("whatever"),
        )
        # Auth failure takes precedence and is still structured.
        body = response.json()
        assert set(body.keys()) == {"error"}
        assert set(body["error"].keys()) >= {"code", "message"}

    async def test_unauthorized_model_rejected(self, client, supabase):
        supabase.add_user("tok", plan="starter")
        response = await client.post(
            "/v1/chat/completions",
            json={**VALID_CHAT_BODY, "model": "nexa-agent"},
            headers=auth_header("tok"),
        )
        assert response.status_code in (402, 403)

    async def test_secure_headers_present(self, client):
        response = await client.get("/v1/health")
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"

    async def test_cors_rejects_unknown_origin(self, client):
        response = await client.get(
            "/v1/health", headers={"Origin": "https://evil.example.com"}
        )
        assert response.headers.get("access-control-allow-origin") is None

    async def test_cors_allows_trusted_origin(self, client):
        response = await client.get(
            "/v1/health", headers={"Origin": "http://localhost:3000"}
        )
        assert response.headers.get("access-control-allow-origin") == (
            "http://localhost:3000"
        )

    async def test_internal_errors_sanitized(self, client, supabase, nvidia):
        supabase.add_user("tok", plan="pro")
        nvidia.fail_with = Exception("db password=hunter2 leak")
        response = await client.post("/v1/chat/completions", json=VALID_CHAT_BODY,
                                     headers=auth_header("tok"))
        text = response.text
        if response.status_code >= 500:
            assert "hunter2" not in text


class TestValidation:
    async def test_missing_messages(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post(
            "/v1/chat/completions", json={"model": "nexa-general"},
            headers=auth_header("tok"))
        assert response.status_code == 400

    async def test_bad_temperature(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post(
            "/v1/chat/completions",
            json={**VALID_CHAT_BODY, "temperature": 5.0},
            headers=auth_header("tok"))
        assert response.status_code == 400

    async def test_bad_max_tokens(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post(
            "/v1/chat/completions",
            json={**VALID_CHAT_BODY, "max_tokens": -5},
            headers=auth_header("tok"))
        assert response.status_code == 400

    async def test_invalid_json(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post(
            "/v1/chat/completions", content=b"{not json",
            headers={**auth_header("tok"), "Content-Type": "application/json"})
        assert response.status_code == 400


class TestAgent:
    async def test_agent_run_requires_auth(self, client):
        response = await client.post("/v1/agent/run", json={"task": "x"})
        assert response.status_code == 401

    async def test_agent_run_validates_task(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post("/v1/agent/run", json={"task": ""},
                                     headers=auth_header("tok"))
        assert response.status_code == 400

    async def test_agent_run_foundation(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.post(
            "/v1/agent/run",
            json={
                "task": "refactor module X",
                "model": "nexa-agent",
                "context": {"repo": "demo"},
                "tools": [{"name": "read_file"}],
                "workspace": {"path": "D:/proj"},
            },
            headers=auth_header("tok"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["pending_tools"] == []  # never executes tools server-side
        assert body["declared_tools"] == ["read_file"]
