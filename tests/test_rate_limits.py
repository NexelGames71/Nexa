"""Rate limit and concurrency tests."""

from __future__ import annotations

import pytest

from nexa.auth import AuthIdentity
from nexa.errors import ConcurrencyLimitError, RateLimitedError, UsageLimitError
from nexa.policies.plans import get_plan_policy
from nexa.policies.ratelimit import RateLimiter
from tests.conftest import VALID_CHAT_BODY, auth_header


def identity(user_id: str = "u-1", plan: str = "starter") -> AuthIdentity:
    return AuthIdentity(user_id=user_id, account_id=user_id, plan=plan)


class TestRateLimiterUnit:
    def test_within_limit(self):
        limiter = RateLimiter()
        for _ in range(3):
            assert limiter.check("k", limit=3, window_seconds=60).allowed

    def test_exceeded_limit(self):
        limiter = RateLimiter()
        for _ in range(2):
            limiter.check("k", limit=2, window_seconds=60)
        result = limiter.check("k", limit=2, window_seconds=60)
        assert not result.allowed
        assert result.retry_after_seconds >= 1

    def test_windows_are_independent(self):
        limiter = RateLimiter()
        limiter.check("user-a", limit=1, window_seconds=60)
        assert limiter.check("user-b", limit=1, window_seconds=60).allowed


class TestPolicyEnforcement:
    async def test_rate_limited_raises(self):
        from nexa.config import Settings
        from nexa.policies.service import PolicyService
        from tests.conftest import FakeSupabase

        service = PolicyService(Settings(), FakeSupabase())
        ident = identity(plan="starter")  # 5 rpm
        policy = await service.enforce_rate_limits(ident, None)
        with pytest.raises(RateLimitedError):
            for _ in range(policy.requests_per_minute + 1):
                await service.enforce_rate_limits(ident, None)

    async def test_model_not_allowed_for_plan(self, client, supabase):
        supabase.add_user("tok", plan="starter")  # only nexa-general
        body = {**VALID_CHAT_BODY, "model": "nexa-code"}
        response = await client.post(
            "/v1/chat/completions", json=body, headers=auth_header("tok")
        )
        assert response.status_code == 402
        assert response.json()["error"]["code"] == "USAGE_LIMIT"

    async def test_unknown_logical_model_rejected(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        body = {**VALID_CHAT_BODY, "model": "gpt-4o"}
        response = await client.post(
            "/v1/chat/completions", json=body, headers=auth_header("tok")
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


class TestConcurrency:
    def test_acquire_and_release(self):
        from nexa.policies.concurrency import ConcurrencyManager

        mgr = ConcurrencyManager()
        mgr.acquire_generation_slot("acct", cap=2)
        mgr.acquire_generation_slot("acct", cap=2)
        with pytest.raises(ConcurrencyLimitError):
            mgr.acquire_generation_slot("acct", cap=2)
        mgr.release_generation_slot("acct")
        mgr.acquire_generation_slot("acct", cap=2)  # works after release

    async def test_concurrent_generations_enforced_over_http(
        self, client, supabase, nvidia, monkeypatch
    ):
        import asyncio

        supabase.add_user("tok", plan="plus")  # 2 concurrent

        class SlowProvider(type(nvidia)):
            async def chat(self, request):
                await asyncio.sleep(0.3)
                return await super().chat(request)

        nvidia.__class__ = SlowProvider

        async def fire():
            return await client.post(
                "/v1/chat/completions",
                json={**VALID_CHAT_BODY},
                headers=auth_header("tok"),
            )

        task_a = asyncio.create_task(fire())
        await asyncio.sleep(0.1)
        task_b = asyncio.create_task(fire())
        await asyncio.sleep(0.1)

        # Both slots held; third request must be rejected immediately.
        response_c = await fire()
        responses = await asyncio.gather(task_a, task_b)

        assert all(r.status_code == 200 for r in responses)
        assert response_c.status_code == 429
        assert response_c.json()["error"]["code"] == "CONCURRENCY_LIMIT"

    async def test_slot_released_on_provider_error(self, client, supabase, nvidia):
        supabase.add_user("tok", plan="pro")

        nvidia.fail_with = RuntimeError("boom")
        bad = await client.post(
            "/v1/chat/completions",
            json={"model": "nexa-general",
                  "messages": [{"role": "user", "content": "x"}], "stream": True},
            headers=auth_header("tok"),
        )
        assert bad.status_code == 200  # SSE started; error arrives in-stream
        nvidia.fail_with = None

        good = await client.post(
            "/v1/chat/completions",
            json={**VALID_CHAT_BODY},
            headers=auth_header("tok"),
        )
        assert good.status_code == 200
