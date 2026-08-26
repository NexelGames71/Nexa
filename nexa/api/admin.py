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

# ============================================================================
# Activity logs (real gateway request history)
# ============================================================================
@router.get("/admin/logs")
async def activity_logs(request: Request, model: str = "", status: str = "",
                        limit: int = 100, offset: int = 0):
    _require_admin(request)
    supa = _state(request).supabase
    import httpx
    url = f"{supa.settings.supabase_url}/rest/v1/ai_requests"
    headers = {
        "apikey": supa.settings.supabase_service_role_key,
        "Authorization": f"Bearer {supa.settings.supabase_service_role_key}",
    }
    params = {"select": "request_id,user_id,account_id,provider,model,status,error_code,"
                        "total_tokens,latency_ms,started_at",
              "order": "started_at.desc",
              "limit": str(min(500, max(1, limit))),
              "offset": str(max(0, offset))}
    if model:
        params["model"] = f"eq.{model}"
    if status:
        params["status"] = f"eq.{status}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url, params=params, headers=headers)
        if response.status_code == 200:
            return {"logs": response.json()}
    except Exception as exc:  # noqa: BLE001
        raise NexaError("INTERNAL_ERROR", f"Log query failed: {type(exc).__name__}")
    return {"logs": []}


# ============================================================================
# Gateway API keys (dashboard-managed, hashed at rest)
# ============================================================================
@router.get("/admin/keys")
async def list_keys(request: Request):
    _require_admin(request)
    supa = _state(request).supabase
    keys = await supa.list_gateway_keys()
    env_count = len(_state(request).settings.parse_gateway_keys())
    return {"keys": keys, "env_keys": env_count}


@router.post("/admin/keys")
async def create_key(body: dict, request: Request):
    _require_admin(request)
    supa = _state(request).supabase
    import secrets as _secrets
    name = str(body.get("name") or "unnamed").strip()
    account_id = str(body.get("account_id") or "").strip()
    plan = str(body.get("plan") or "starter").strip()
    if not name or not account_id:
        raise NexaError("INVALID_REQUEST", "name and account_id are required")
    token = "nxkey_" + _secrets.token_hex(16)
    ok = await supa.create_gateway_key(
        name=name, key_hash=supa.hash_key(token),
        key_prefix=token[:12], account_id=account_id, plan=plan,
        created_by="admin")
    if not ok:
        raise NexaError("INTERNAL_ERROR", "Key write failed")
    await supa.audit("key.created", token[:12], {"account_id": account_id, "plan": plan})
    return {"success": True, "token": token,
            "note": "Store this token now — it is never shown again."}


@router.delete("/admin/keys/{key_id}")
async def revoke_key(key_id: str, request: Request):
    _require_admin(request)
    ok = await _state(request).supabase.set_gateway_key_enabled(key_id, False)
    await _state(request).supabase.audit("key.revoked", key_id)
    return {"success": ok}


# ============================================================================
# Usage limits: per-account overrides (ai_account_limits)
# ============================================================================
@router.get("/admin/limits")
async def list_limits(request: Request):
    _require_admin(request)
    supa = _state(request).supabase
    overrides = await supa.get_account_limit_rows()
    profiles = await supa.list_profiles()
    return {"overrides": overrides, "accounts": profiles}


@router.put("/admin/limits/{account_id}")
async def set_limit(account_id: str, body: dict, request: Request):
    _require_admin(request)
    supa = _state(request).supabase
    row = {"account_id": account_id}
    for field in ("plan_override", "requests_per_minute", "requests_per_hour",
                  "concurrent_generations", "monthly_token_limit"):
        if field in body and body[field] is not None:
            row[field] = body[field]
    ok = await supa.upsert_account_limit_row(row)
    await supa.audit("limits.updated", account_id, row)
    return {"success": ok}


# ============================================================================
# Subscriptions & teams (read-only)
# ============================================================================
@router.get("/admin/subscriptions")
async def subscriptions(request: Request):
    _require_admin(request)
    supa = _state(request).supabase
    import httpx
    headers = {
        "apikey": supa.settings.supabase_service_role_key,
        "Authorization": f"Bearer {supa.settings.supabase_service_role_key}",
    }
    base = f"{supa.settings.supabase_url}/rest/v1"
    out = {"profiles": [], "subscriptions": []}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r1 = await client.get(base + "/profiles",
                                  params={"select": "id,email,plan,created_at",
                                          "order": "created_at.desc", "limit": "200"},
                                  headers=headers)
            if r1.status_code == 200:
                out["profiles"] = r1.json()
            r2 = await client.get(base + "/subscriptions",
                                  params={"select": "id,user_id,organization_id,plan_id,status,seats,current_period_end",
                                          "order": "created_at.desc", "limit": "100"},
                                  headers=headers)
            if r2.status_code == 200:
                out["subscriptions"] = r2.json()
    except Exception as exc:  # noqa: BLE001
        raise NexaError("INTERNAL_ERROR", f"Subscription query failed: {type(exc).__name__}")
    return out


@router.get("/admin/teams")
async def teams(request: Request):
    _require_admin(request)
    supa = _state(request).supabase
    import httpx
    headers = {
        "apikey": supa.settings.supabase_service_role_key,
        "Authorization": f"Bearer {supa.settings.supabase_service_role_key}",
    }
    base = f"{supa.settings.supabase_url}/rest/v1"
    out = {"teams": []}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r1 = await client.get(base + "/organizations",
                                  params={"select": "id,name,slug,owner_id,created_at"},
                                  headers=headers)
            orgs = r1.json() if r1.status_code == 200 else []
            for org in orgs:
                members = []
                r2 = await client.get(base + "/organization_members",
                                      params={"select": "user_id,role",
                                              "organization_id": f"eq.{org['id']}"},
                                      headers=headers)
                if r2.status_code == 200:
                    members = r2.json()
                out["teams"].append({**org, "members": members})
    except Exception as exc:  # noqa: BLE001
        raise NexaError("INTERNAL_ERROR", f"Teams query failed: {type(exc).__name__}")
    return out


# ============================================================================
# Service configuration (system prompts, routing rules, agent config)
# ============================================================================
CONFIG_KEYS = ("system_prompt", "routing_rules", "agent_config")


@router.get("/admin/config/{key}")
async def get_config(key: str, request: Request):
    _require_admin(request)
    if key not in CONFIG_KEYS:
        raise NexaError("INVALID_REQUEST", f"Unknown config key '{key}'")
    supa = _state(request).supabase
    row = await supa.get_config(key)
    return {"key": key, "value": (row or {}).get("value", {}),
            "updated_by": (row or {}).get("updated_by"),
            "updated_at": (row or {}).get("updated_at")}


@router.put("/admin/config/{key}")
async def put_config(key: str, body: dict, request: Request):
    _require_admin(request)
    if key not in CONFIG_KEYS:
        raise NexaError("INVALID_REQUEST", f"Unknown config key '{key}'")
    supa = _state(request).supabase
    ok = await supa.put_config(key, body.get("value", {}), "admin")
    if not ok:
        raise NexaError("INTERNAL_ERROR", "Config write failed")
    await supa.audit("config.published", key)
    return {"success": True}


# ============================================================================
# Client-facing published config (Nexcoder reads this)
# ============================================================================
@router.get("/config/{key}")
async def public_config(key: str, request: Request):
    state = _state(request)
    identity = await state.authenticator.authenticate_request(
        request.headers.get("authorization"))
    if key not in CONFIG_KEYS:
        raise NexaError("INVALID_REQUEST", f"Unknown config key '{key}'")
    supa = state.supabase
    row = await supa.get_config(key)
    return {"key": key, "value": (row or {}).get("value", {})}

# ============================================================================
# Webhooks — outgoing event notifications
# ============================================================================
@router.get("/admin/webhooks")
async def list_webhooks(request: Request):
    _require_admin(request)
    hooks = await _state(request).supabase.list_webhooks()
    return {"webhooks": hooks}


@router.post("/admin/webhooks")
async def create_webhook(body: dict, request: Request):
    _require_admin(request)
    url = str(body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise NexaError("INVALID_REQUEST", "A valid https URL is required")
    ok = await _state(request).supabase.create_webhook({
        "url": url,
        "secret": str(body.get("secret") or ""),
        "events": body.get("events") or ["model.updated", "provider.failure"],
        "enabled": bool(body.get("enabled", True)),
    })
    if not ok:
        raise NexaError("INTERNAL_ERROR", "Webhook write failed")
    await supa.audit("webhook.created", url)
    return {"success": True}


@router.delete("/admin/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, request: Request):
    _require_admin(request)
    ok = await _state(request).supabase.delete_webhook(webhook_id)
    return {"success": ok}


@router.post("/admin/webhooks/test")
async def test_webhook(body: dict, request: Request):
    """POST a test event to an arbitrary webhook URL."""
    _require_admin(request)
    import httpx
    target = str(body.get("url") or "").strip()
    if not target.startswith(("http://", "https://")):
        raise NexaError("INVALID_REQUEST", "A valid https URL is required")
    payload = {"event": "test", "service": "nexa", "timestamp": _state(request).settings.env}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(target, json=payload, timeout=8.0)
        return {"success": True, "status": response.status_code}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}"}


# ============================================================================
# Backups — configuration snapshots (catalog + config + limits)
# ============================================================================
@router.get("/admin/backups")
async def list_backups(request: Request):
    _require_admin(request)
    supa = _state(request).supabase
    backups = await supa.list_backups()
    for b in backups:
        b.pop("payload", None)
    return {"backups": backups}


@router.post("/admin/backups")
async def create_backup(request: Request):
    _require_admin(request)
    state = _state(request)
    supa = state.supabase
    catalog = await state.catalog.get_models(include_disabled=True)
    payload: dict = {
        "catalog": catalog,
        "limits": await supa.get_account_limit_rows(),
    }
    for key in ("system_prompt", "routing_rules", "agent_config", "integrations"):
        row = await supa.get_config(key)
        payload[key] = (row or {}).get("value", {})
    ok = await supa.create_backup(
        label=f"config snapshot {len(catalog)} models",
        payload=payload, created_by="admin")
    if not ok:
        raise NexaError("INTERNAL_ERROR", "Backup write failed")
    return {"success": True}


@router.get("/admin/backups/{backup_id}")
async def download_backup(backup_id: str, request: Request):
    _require_admin(request)
    backup = await _state(request).supabase.get_backup(backup_id)
    if backup is None:
        raise NexaError("MODEL_UNAVAILABLE", "Backup not found")
    return backup


@router.delete("/admin/backups/{backup_id}")
async def delete_backup(backup_id: str, request: Request):
    _require_admin(request)
    ok = await _state(request).supabase.delete_backup(backup_id)
    return {"success": ok}


# ============================================================================
# Admin audit trail
# ============================================================================
@router.get("/admin/audit")
async def audit_logs(request: Request, limit: int = 150):
    _require_admin(request)
    supa = _state(request).supabase
    return {"audit": await supa.list_audit(min(500, max(1, limit)))}
