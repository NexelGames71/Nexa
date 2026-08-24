"""GET /v1/models — logical model catalog (plan-filtered)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request

from nexa.api.deps import current_identity, get_nexa_state
from nexa.appstate import NexaState
from nexa.auth import AuthIdentity, apply_identity
from nexa.context import RequestContext
from nexa.routing.catalog import CATALOG, catalog_payload

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
        if m.id not in policy.allowed_models:
            continue
        models.append(
            {
                "id": m.id,
                "display_name": m.display_name,
                "capabilities": m.capabilities,
                "description": m.description,
                "object": "model",
                "owned_by": "nexa",
            }
        )
    return {"models": models, "data": models}
