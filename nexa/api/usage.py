"""GET /v1/usage — plan entitlements and current billing-period usage.

One call powering client-side plan indicators, upgrade prompts and the
usage/limits settings surface.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request

from nexa.api.deps import current_identity, get_nexa_state
from nexa.appstate import NexaState
from nexa.auth import AuthIdentity, apply_identity
from nexa.context import RequestContext
from nexa.policies.plans import PLAN_RANK, minimum_plan_for_model
from nexa.routing.catalog import CATALOG

router = APIRouter()


@router.get("/usage")
async def get_usage(
    http_request: Request,
    state: NexaState = Depends(get_nexa_state),
    identity: AuthIdentity = Depends(current_identity),
) -> dict:
    ctx: RequestContext | None = getattr(http_request.state, "nexa_ctx", None)
    if ctx is not None:
        apply_identity(ctx, identity)

    policy = state.policies.plan_policy(identity)
    overrides = await state.policies._overrides(identity.account_id)

    monthly_limit = overrides.monthly_token_limit or policy.monthly_token_limit
    usage, persistence_ok = await state.supabase.monthly_usage(identity.account_id)
    total_used = int(usage.get("total_tokens", 0))
    windows = await state.usage_windows.snapshot(identity.account_id, policy)

    models = []
    for m in CATALOG:
        available = m.id in policy.allowed_models
        models.append(
            {
                "id": m.id,
                "display_name": m.display_name,
                "available": available,
                "required_plan": None if available else minimum_plan_for_model(m.id),
            }
        )

    return {
        "plan": identity.plan,
        "plan_rank": PLAN_RANK.get(identity.plan, 0),
        "persistence": "ok" if persistence_ok else "unavailable",
        "persistence_hint": None if persistence_ok else (
            "Usage storage is not active. Apply supabase/migrations/"
            "0001_full_nexcoder_nexa.sql and 0002_usage_rpc.sql."),
        "limits": {
            "requests_per_minute": overrides.requests_per_minute
            or policy.requests_per_minute,
            "requests_per_hour": overrides.requests_per_hour
            or policy.requests_per_hour,
            "concurrent_generations": overrides.concurrent_generations
            or policy.concurrent_generations,
            "monthly_token_limit": monthly_limit,
            "maximum_context": policy.maximum_context,
        },
        "usage": {
            "period": "month_to_date",
            "requests": int(usage.get("requests", 0)),
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": total_used,
        },
        "remaining_tokens": max(0, monthly_limit - total_used),
        # 5-hour + daily + weekly windows (server-authoritative; spec §14/§21).
        "five_hour": windows["five_hour"],
        "daily": windows["daily"],
        "weekly": windows["weekly"],
        "models": models,
        "upgrade_url": "https://nexcoder.trynexa-ai.com/pricing",
    }
