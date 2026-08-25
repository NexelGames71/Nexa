"""Admin API: manage the model catalog without touching client code.

Auth: NEXA_ADMIN_TOKEN bearer token (server-side env). When the token is
not configured, admin routes are disabled entirely.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from nexa.config import Settings
from nexa.errors import AUTHORIZATION_FAILED, AuthenticationError, NexaError
from nexa.api.command_center import PAGE as _CC_PAGE
from nexa.services.catalog_service import CatalogService

router = APIRouter()


def _require_admin(request: Request) -> Settings:
    state = request.app.state.nexa
    token = state.settings.admin_token
    if not token:
        raise NexaError(AUTHORIZATION_FAILED, "Admin API is disabled on this deployment")
    header = request.headers.get("authorization", "")
    if header != f"Bearer {token}":
        raise AuthenticationError("Invalid admin token")
    return state.settings


def _state(request: Request):
    return request.app.state.nexa


@router.get("/admin/catalog")
async def list_catalog(request: Request):
    _require_admin(request)
    state = _state(request)
    models = await state.catalog.get_models(include_disabled=True)
    return {"models": [CatalogService.normalize(m) for m in models]}


@router.put("/admin/catalog/{model_id:path}")
async def upsert_model(model_id: str, body: dict[str, Any], request: Request):
    _require_admin(request)
    state = _state(request)
    if not isinstance(body, dict) or not model_id.strip():
        raise NexaError("INVALID_REQUEST", "Model id and body are required")

    row = {
        "logical_id": model_id.strip(),
        "display_name": str(body.get("display_name") or model_id),
        "capabilities": body.get("capabilities") or ["chat", "streaming"],
        "provider": str(body.get("provider") or "nvidia"),
        "provider_model": str(body.get("provider_model") or model_id),
        "context_window": int(body.get("context_window") or 65536),
        "max_output_tokens": int(body.get("max_output_tokens") or 8192),
        "requires_plan": str(body.get("requires_plan") or "starter"),
        "enabled": bool(body.get("enabled", True)),
        "sort_order": int(body.get("sort_order") or 100),
    }
    ok = await state.supabase.upsert_model_catalog_row(row)
    if not ok:
        raise NexaError("INTERNAL_ERROR", "Catalog write failed")
    state.catalog.invalidate()
    return {"success": True, "model": CatalogService.normalize(row)}


@router.delete("/admin/catalog/{model_id:path}")
async def delete_model(model_id: str, request: Request):
    _require_admin(request)
    state = _state(request)
    ok = await state.supabase.delete_model_catalog_row(model_id)
    state.catalog.invalidate()
    return {"success": ok}


@router.get("/admin/providers")
async def provider_status(request: Request):
    _require_admin(request)
    state = _state(request)
    return {
        "providers": {
            name: {"configured": bool(getattr(p, "configured", True))}
            for name, p in state.providers.items()
        },
    }


@router.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Nexa Command Center — admin dashboard SPA."""
    return HTMLResponse(_CC_PAGE)
