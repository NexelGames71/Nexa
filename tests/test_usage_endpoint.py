"""Tests for GET /v1/usage and per-model availability in GET /v1/models."""

from __future__ import annotations

from tests.conftest import auth_header

STARTER = "starter"
PRO = "pro"


class TestModelsAvailability:
    async def test_starter_sees_all_models_with_flags(self, client, supabase):
        supabase.add_user("tok", plan=STARTER)
        response = await client.get("/v1/models", headers=auth_header("tok"))
        assert response.status_code == 200
        models = {m["id"]: m for m in response.json()["models"]}
        # All four catalog models are listed...
        assert len(models) == 4
        # ...flash models available, nemotron gated with required_plan.
        assert models["stepfun-ai/step-3.7-flash"]["available"] is True
        assert models["deepseek-ai/deepseek-v4-flash-0731"]["available"] is True
        assert models["nvidia/nemotron-3-ultra-550b-a55b"]["available"] is False
        assert models["nvidia/nemotron-3-ultra-550b-a55b"]["required_plan"] == "plus"
        assert models["nvidia/nemotron-3-super-120b-a12b"]["required_plan"] == "plus"

    async def test_pro_sees_everything_available(self, client, supabase):
        supabase.add_user("tok", plan=PRO)
        response = await client.get("/v1/models", headers=auth_header("tok"))
        models = response.json()["models"]
        assert all(m["available"] for m in models)
        assert all(m["required_plan"] is None for m in models)


class TestUsageEndpoint:
    async def test_usage_requires_auth(self, client):
        response = await client.get("/v1/usage")
        assert response.status_code == 401

    async def test_usage_payload_shape(self, client, supabase):
        supabase.add_user("tok", user_id="u-5", plan=PRO)
        response = await client.get("/v1/usage", headers=auth_header("tok"))
        assert response.status_code == 200
        body = response.json()
        assert body["plan"] == PRO
        limits = body["limits"]
        assert limits["requests_per_minute"] == 30
        assert limits["concurrent_generations"] == 4
        assert limits["monthly_token_limit"] == 10_000_000
        assert body["usage"]["requests"] == 0
        assert body["remaining_tokens"] == 10_000_000
        assert len(body["models"]) == 4
        assert body["upgrade_url"].startswith("https://")

    async def test_usage_reflects_recorded_requests(self, client, supabase):
        supabase.add_user("tok", user_id="u-5", plan=PRO)

        async def fake_usage(account_id):
            return ({"requests": 12, "input_tokens": 100,
                     "output_tokens": 50, "total_tokens": 150}, True)

        supabase.monthly_usage = fake_usage
        response = await client.get("/v1/usage", headers=auth_header("tok"))
        body = response.json()
        assert body["usage"]["requests"] == 12
        assert body["usage"]["total_tokens"] == 150
        assert body["remaining_tokens"] == 10_000_000 - 150

    async def test_starter_usage_shows_upgrade_models(self, client, supabase):
        supabase.add_user("tok", plan=STARTER)
        response = await client.get("/v1/usage", headers=auth_header("tok"))
        models = {m["id"]: m for m in response.json()["models"]}
        assert models["nvidia/nemotron-3-super-120b-a12b"]["available"] is False
        assert models["nvidia/nemotron-3-super-120b-a12b"]["required_plan"] == "plus"
