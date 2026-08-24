"""Centralized plan policies.

Plan limits live here and only here. API routes never embed plan logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanPolicy:
    id: str
    requests_per_minute: int
    requests_per_hour: int
    concurrent_generations: int
    monthly_token_limit: int
    allowed_models: frozenset[str]
    maximum_context: int
    # Usage windows (token units): fast 5-hour allowance + slower weekly
    # allowance with exactly one complimentary renewal per weekly cycle.
    five_hour_limit: int = 0
    weekly_limit: int = 0
    weekly_renewal_count: int = 1


_ALL_MODELS = frozenset({
    "stepfun-ai/step-3.7-flash",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
    "deepseek-ai/deepseek-v4-flash-0731",
})

# Lighter/cheaper models available on the entry plan.
_ENTRY_MODELS = frozenset({
    "stepfun-ai/step-3.7-flash",
    "deepseek-ai/deepseek-v4-flash-0731",
})

PLAN_POLICIES: dict[str, PlanPolicy] = {
    "starter": PlanPolicy(
        id="starter",
        requests_per_minute=5,
        requests_per_hour=50,
        concurrent_generations=1,
        monthly_token_limit=200_000,
        allowed_models=_ENTRY_MODELS,
        maximum_context=8_192,
        five_hour_limit=50_000,
        weekly_limit=200_000,
        weekly_renewal_count=1,
    ),
    "plus": PlanPolicy(
        id="plus",
        requests_per_minute=10,
        requests_per_hour=200,
        concurrent_generations=2,
        monthly_token_limit=2_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=16_384,
        five_hour_limit=250_000,
        weekly_limit=1_000_000,
        weekly_renewal_count=1,
    ),
    "pro": PlanPolicy(
        id="pro",
        requests_per_minute=30,
        requests_per_hour=600,
        concurrent_generations=4,
        monthly_token_limit=10_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=32_768,
        five_hour_limit=750_000,
        weekly_limit=3_000_000,
        weekly_renewal_count=1,
    ),
    "premium": PlanPolicy(
        id="premium",
        requests_per_minute=60,
        requests_per_hour=1_500,
        concurrent_generations=8,
        monthly_token_limit=30_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=65_536,
        five_hour_limit=2_000_000,
        weekly_limit=8_000_000,
        weekly_renewal_count=1,
    ),
    "business-standard": PlanPolicy(
        id="business-standard",
        requests_per_minute=120,
        requests_per_hour=3_000,
        concurrent_generations=12,
        monthly_token_limit=60_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=65_536,
        five_hour_limit=4_000_000,
        weekly_limit=15_000_000,
        weekly_renewal_count=1,
    ),
    "business-plus": PlanPolicy(
        id="business-plus",
        requests_per_minute=240,
        requests_per_hour=6_000,
        concurrent_generations=24,
        monthly_token_limit=150_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=131_072,
        five_hour_limit=8_000_000,
        weekly_limit=30_000_000,
        weekly_renewal_count=1,
    ),
    "enterprise": PlanPolicy(
        id="enterprise",
        requests_per_minute=600,
        requests_per_hour=15_000,
        concurrent_generations=64,
        monthly_token_limit=500_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=131_072,
        five_hour_limit=20_000_000,
        weekly_limit=75_000_000,
        weekly_renewal_count=1,
    ),
}


def get_plan_policy(plan_id: str) -> PlanPolicy:
    return PLAN_POLICIES.get(plan_id) or PLAN_POLICIES["starter"]


# Upgrade ordering (low -> high). Team plans sit above premium.
PLAN_RANK: dict[str, int] = {
    "starter": 0,
    "plus": 1,
    "pro": 2,
    "premium": 3,
    "business-standard": 4,
    "business-plus": 5,
    "enterprise": 6,
}


def minimum_plan_for_model(model_id: str) -> str | None:
    """Cheapest plan that includes the model, or None if no plan gates it."""
    candidates = [
        (PLAN_RANK.get(pid, 99), pid)
        for pid, policy in PLAN_POLICIES.items()
        if model_id in policy.allowed_models
    ]
    return min(candidates)[1] if candidates else None

