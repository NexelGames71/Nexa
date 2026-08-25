"""GET /v1/models — admin-managed catalog with plan availability.

Served dynamically from ai_model_catalog (30s cache) so model changes,
context windows and gating propagate to clients without redeploys.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from nexa.api.deps import current_identity, get_nexa_state
from nexa.appstate import NexaState
from nexa.auth import AuthIdentity, apply_identity
from nexa.context import RequestContext
from nexa.policies.plans import PLAN_RANK
from nexa.services.catalog_service import CatalogService

router = APIRouter()


def _availability(catalog_model: dict, policy) -> tuple[bool, str | None]:
    """(available, required_plan) from requires_plan rank, with a fallback
    to the static plan model sets for entries without requires_plan."""
    required = catalog_model.get("requires_plan")
    if required:
        need = PLAN_RANK.get(required, 0)
        have = PLAN_RANK.get(policy.id, 0)
        return have >= need, (None if have >= need else required)
    model_id = catalog_model.get("logical_id") or catalog_model.get("id", "")
    if model_id in policy.allowed_models:
        return True, None
    return False, None


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
    rows = await state.catalog.get_models()
    models = []
    for row in rows:
        m = CatalogService.normalize(row)
        available, required_plan = _availability(row, policy)
        models.append(
            {
                **m,
                "object": "model",
                "owned_by": "nexa",
                "available": available,
                "required_plan": required_plan,
            }
        )
    return {"models": models, "data": models}
