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
    ),
    "plus": PlanPolicy(
        id="plus",
        requests_per_minute=10,
        requests_per_hour=200,
        concurrent_generations=2,
        monthly_token_limit=2_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=16_384,
    ),
    "pro": PlanPolicy(
        id="pro",
        requests_per_minute=30,
        requests_per_hour=600,
        concurrent_generations=4,
        monthly_token_limit=10_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=32_768,
    ),
    "premium": PlanPolicy(
        id="premium",
        requests_per_minute=60,
        requests_per_hour=1_500,
        concurrent_generations=8,
        monthly_token_limit=30_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=65_536,
    ),
    "business-standard": PlanPolicy(
        id="business-standard",
        requests_per_minute=120,
        requests_per_hour=3_000,
        concurrent_generations=12,
        monthly_token_limit=60_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=65_536,
    ),
    "business-plus": PlanPolicy(
        id="business-plus",
        requests_per_minute=240,
        requests_per_hour=6_000,
        concurrent_generations=24,
        monthly_token_limit=150_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=131_072,
    ),
    "enterprise": PlanPolicy(
        id="enterprise",
        requests_per_minute=600,
        requests_per_hour=15_000,
        concurrent_generations=64,
        monthly_token_limit=500_000_000,
        allowed_models=_ALL_MODELS,
        maximum_context=131_072,
    ),
}


def get_plan_policy(plan_id: str) -> PlanPolicy:
    return PLAN_POLICIES.get(plan_id) or PLAN_POLICIES["starter"]

