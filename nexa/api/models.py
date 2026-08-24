"""GET /v1/models — full catalog with per-plan availability.

Every catalog model is returned (not just allowed ones) so clients can show
which models need an upgrade. `available` reflects the caller's plan.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from nexa.api.deps import current_identity, get_nexa_state
from nexa.appstate import NexaState
from nexa.auth import AuthIdentity, apply_identity
from nexa.context import RequestContext
from nexa.policies.plans import minimum_plan_for_model
from nexa.routing.catalog import CATALOG

router = APIRouter()


@router.get("/models")
async def list_models(
    http_request: Request,
    state: NexaState = Depends(get_nexa_state),
    identity: AuthIdentity = Depends(current_identity),
) -> dict:
    ctx: RequestContext | None = getattr(http_request.state, "nexa_ctx", None)
    if ctx is not None:
        apply_identity(ctx, identity)
    policy = state.policies.plan_policy(identity)
    models = []
    for m in CATALOG:
        available = m.id in policy.allowed_models
        models.append(
            {
                "id": m.id,
                "display_name": m.display_name,
                "capabilities": m.capabilities,
                "description": m.description,
                "object": "model",
                "owned_by": "nexa",
                "available": available,
                "required_plan": None if available else minimum_plan_for_model(m.id),
            }
        )
    return {"models": models, "data": models}
