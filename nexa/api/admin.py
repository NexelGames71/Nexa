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


@router.put("/admin/catalog/{model_id}")
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


@router.delete("/admin/catalog/{model_id}")
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


_ADMIN_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Nexa Admin</title>
<style>
 body{font-family:ui-sans-serif,system-ui;background:#0d0d14;color:#e8e8f0;margin:0;padding:32px}
 h1{font-size:20px} table{border-collapse:collapse;width:100%;margin:16px 0}
 th,td{padding:8px 10px;border-bottom:1px solid #26263a;text-align:left;font-size:13px}
 th{color:#9a9ab8;text-transform:uppercase;font-size:10px;letter-spacing:.5px}
 input,select,button{background:#1a1a28;color:#e8e8f0;border:1px solid #33334a;border-radius:6px;padding:6px 10px;font-size:13px}
 button{cursor:pointer} button:hover{background:#2a2a40}
 .row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
 #msg{margin:12px 0;color:#ffb020;font-size:13px;min-height:18px}
 .en{color:#46a758}.dis{color:#e5484d}
</style></head><body>
<h1>Nexa Model Catalog</h1>
<div class="row"><input id="token" type="password" placeholder="Admin token" style="width:280px">
<button onclick="load()">Connect</button></div>
<div id="msg"></div>
<table id="tbl"><thead><tr><th>Model</th><th>Provider</th><th>Context</th><th>Max out</th><th>Min plan</th><th>Enabled</th><th></th></tr></thead><tbody></tbody></table>
<h3>Upsert model</h3>
<div class="row">
 <input id="m_id" placeholder="model id (e.g. org/model)">
 <input id="m_name" placeholder="display name">
 <select id="m_provider"><option>nvidia</option><option>openrouter</option></select>
 <input id="m_pmodel" placeholder="provider model id">
</div>
<div class="row">
 <input id="m_ctx" type="number" value="65536" placeholder="context window">
 <input id="m_out" type="number" value="8192" placeholder="max output">
 <select id="m_plan"><option>starter</option><option>plus</option><option>pro</option><option>premium</option><option>business-standard</option><option>business-plus</option><option>enterprise</option></select>
 <label style="font-size:13px"><input id="m_en" type="checkbox" checked> enabled</label>
 <button onclick="upsert()">Save</button>
</div>
<script>
const H = () => ({'Authorization': 'Bearer ' + document.getElementById('token').value, 'Content-Type': 'application/json'});
const msg = (t) => document.getElementById('msg').textContent = t;
async function load() {
  const r = await fetch('/v1/admin/catalog', {headers: H()});
  if (!r.ok) { msg('Failed: HTTP ' + r.status); return; }
  msg('Loaded ' + new Date().toLocaleTimeString());
  const {models} = await r.json();
  const tb = document.querySelector('#tbl tbody');
  tb.innerHTML = '';
  for (const m of models) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${m.id}</td><td>${m.provider}</td><td>${m.context_window ?? '-'}</td>
      <td>${m.max_output_tokens ?? '-'}</td><td>${m.requires_plan ?? '-'}</td>
      <td class="${m.enabled ? 'en' : 'dis'}">${m.enabled}</td>
      <td><button onclick="del('${m.id}')">Remove</button>
      <button onclick="edit('${m.id}','${m.display_name}','${m.provider}','${m.context_window ?? ''}','${m.max_output_tokens ?? ''}','${m.requires_plan ?? ''}',${m.enabled})">Edit</button></td>`;
    tb.appendChild(tr);
  }
}
function edit(id, name, provider, ctx, out, plan, en) {
  m_id.value = id; m_name.value = name; m_provider.value = provider;
  m_pmodel.value = id; m_ctx.value = ctx; m_out.value = out;
  m_plan.value = plan; m_en.checked = en;
}
async function upsert() {
  const body = {
    display_name: m_name.value, provider: m_provider.value,
    provider_model: m_pmodel.value || m_id.value,
    context_window: +m_ctx.value, max_output_tokens: +m_out.value,
    requires_plan: m_plan.value, enabled: m_en.checked,
  };
  const r = await fetch('/v1/admin/catalog/' + encodeURIComponent(m_id.value),
    {method: 'PUT', headers: H(), body: JSON.stringify(body)});
  msg(r.ok ? 'Saved' : 'Failed: HTTP ' + r.status);
  if (r.ok) load();
}
async function del(id) {
  const r = await fetch('/v1/admin/catalog/' + encodeURIComponent(id),
    {method: 'DELETE', headers: H()});
  msg(r.ok ? 'Removed' : 'Failed'); if (r.ok) load();
}
</script></body></html>"""


@router.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Minimal admin dashboard (token entered in-page, sent per request)."""
    return HTMLResponse(_ADMIN_PAGE)
