"""Usage window tests: 5-hour pool, weekly cycle, renewal, concurrency,
idempotency — per the Nexa usage-window spec."""

from __future__ import annotations

import asyncio

import pytest

from nexa.policies.plans import PlanPolicy
from nexa.policies.usage_windows import FIVE_HOUR_SECONDS, WEEK_SECONDS, UsageService
from tests.conftest import VALID_CHAT_BODY, auth_header


class _NoDbSupabase:
    class settings:
        usage_persistence_configured = False


def policy(five_hour=100, daily=100_000, weekly=1000, renewal=1) -> PlanPolicy:
    base = PlanPolicy(
        id="test", requests_per_minute=1000, requests_per_hour=100000,
        concurrent_generations=10, monthly_token_limit=10**9,
        allowed_models=frozenset({"stepfun-ai/step-3.7-flash"}),
        maximum_context=180_000)
    return PlanPolicy(**{**base.__dict__, "five_hour_limit": five_hour,
                         "daily_limit": daily,
                         "weekly_limit": weekly,
                         "weekly_renewal_count": renewal})


class TestFiveHour:
    async def test_first_request_starts_window(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        snap = await svc.snapshot("acct", policy())
        assert snap["usage_started"] is False
        await svc.authorize("acct", policy(), 10, "r1")
        snap = await svc.snapshot("acct", policy())
        assert snap["usage_started"] is True
        assert snap["five_hour"]["used"] == 10
        assert snap["five_hour"]["reset_in_seconds"] is not None
        assert snap["five_hour"]["reset_in_seconds"] <= FIVE_HOUR_SECONDS

    async def test_usage_accumulates_and_blocks_at_limit(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=100)
        assert (await svc.authorize("a", pol, 60, "r1")).allowed
        blocked = await svc.authorize("a", pol, 60, "r2")  # would exceed
        assert not blocked.allowed
        assert blocked.window == "five_hour"
        ok = await svc.authorize("a", pol, 40, "r3")  # exactly fills
        assert ok.allowed
        assert (await svc.authorize("a", pol, 1, "r4")).allowed is False

    async def test_five_hour_reset_does_not_touch_weekly(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=100, weekly=1000)
        await svc.authorize("a", pol, 100, "r1")
        state = svc._memory["a"]
        # Simulate window expiry.
        state.five_hour_window_ends_at -= FIVE_HOUR_SECONDS + 1
        assert (await svc.authorize("a", pol, 10, "r2")).allowed
        assert state.five_hour_used == 10  # reset then consumed 10
        assert state.weekly_used == 110    # weekly keeps accumulating


class TestWeekly:
    async def test_weekly_cycle_and_reset(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=1000, weekly=500)
        await svc.authorize("a", pol, 400, "r1")
        state = svc._memory["a"]
        assert state.weekly_used == 400
        state.weekly_cycle_ends_at -= WEEK_SECONDS + 1  # expire cycle
        await svc.authorize("a", pol, 100, "r2")
        assert state.weekly_used == 100          # reset then consumed
        assert state.weekly_renewals_used == 0   # eligibility restored

    async def test_weekly_exhaustion_renewal_then_block(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=10_000, weekly=1000, renewal=1)

        assert (await svc.authorize("a", pol, 1000, "r1")).allowed
        # Weekly exhausted -> renewal grants atomically on next authorize.
        decision = await svc.authorize("a", pol, 1, "r2")
        assert decision.allowed and decision.renewal_granted
        # Renewed allowance usable.
        assert (await svc.authorize("a", pol, 999, "r3")).allowed
        # Renewal already used: blocked until the 7-day reset.
        blocked = await svc.authorize("a", pol, 1, "r4")
        assert not blocked.allowed and blocked.window == "weekly"
        assert blocked.retry_after_seconds > 0

        # Weekly reset restores usage AND renewal eligibility.
        state = svc._memory["a"]
        state.weekly_cycle_ends_at -= WEEK_SECONDS + 1
        assert (await svc.authorize("a", pol, 500, "r5")).allowed
        assert state.weekly_renewals_used == 0


class TestConcurrencyAndIdempotency:
    async def test_concurrent_requests_cannot_overspend(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=1000, weekly=5000)
        results = await asyncio.gather(*[
            svc.authorize("a", pol, 300, f"r{i}") for i in range(10)
        ])
        allowed = [r for r in results if r.allowed]
        # 300 x 10 = 3000 > 1000: only 3 may pass, no partial overspend.
        assert len(allowed) == 3
        state = svc._memory["a"]
        assert state.five_hour_used == 900
        assert state.weekly_used == 900

    async def test_idempotent_request_id_charges_once(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=1000, weekly=5000)
        first = await svc.authorize("a", pol, 100, "same-id")
        second = await svc.authorize("a", pol, 100, "same-id")
        assert first.allowed and second.allowed
        assert svc._memory["a"].five_hour_used == 100  # charged once

    async def test_finalize_reconciles_actual_usage(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=1000, weekly=5000)
        await svc.authorize("a", pol, 500, "r1")   # reserved 500
        await svc.finalize("a", "r1", 120)         # actually 120
        assert svc._memory["a"].five_hour_used == 120

    async def test_release_gives_back_on_failure(self):
        svc = UsageService.__new__(UsageService)
        svc.supabase = _NoDbSupabase()
        svc._memory = {}
        svc._locks = {}
        pol = policy(five_hour=1000, weekly=5000)
        await svc.authorize("a", pol, 500, "r1")
        await svc.release("a", "r1")
        assert svc._memory["a"].five_hour_used == 0


class TestHttpEnforcement:
    async def test_five_hour_limit_http_response(self, client, supabase, nvidia):
        supabase.add_user("tok", plan="starter")
        # Provider reports ~180k real tokens per call, so finalized usage
        # (not just reservations) accumulates toward the 500k starter limit.
        from nexa.providers.base import ChatResponse, Usage as PUsage

        async def big_chat(request):
            return ChatResponse(content="ok", model=request.model,
                                usage=PUsage(input_tokens=180_000, output_tokens=0))
        nvidia.chat = big_chat
        big = "x" * (180_000 * 3)
        statuses = []
        for _ in range(3):
            response = await client.post(
                "/v1/chat/completions",
                json={"model": "stepfun-ai/step-3.7-flash",
                      "messages": [{"role": "user", "content": big}]},
                headers=auth_header("tok"))
            statuses.append(response.status_code)
        assert statuses[:2] == [200, 200]
        assert statuses[2] == 429
        body = response.json()["error"]
        assert body["code"] == "FIVE_HOUR_LIMIT_REACHED"
        assert "reset_at" in body["details"]
        assert response.headers.get("retry-after")

    async def test_usage_endpoint_exposes_windows(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        await client.post("/v1/chat/completions", json=VALID_CHAT_BODY,
                          headers=auth_header("tok"))
        response = await client.get("/v1/usage", headers=auth_header("tok"))
        body = response.json()
        assert body["five_hour"]["used"] > 0
        assert body["weekly"]["used"] > 0
        assert body["weekly"]["renewal_count"] == 1
        assert body["five_hour"]["reset_in_seconds"] is not None

