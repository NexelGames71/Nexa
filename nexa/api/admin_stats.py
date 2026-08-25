"""Admin dashboard statistics: live operational KPIs from ai_requests."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter()

from nexa.api.admin import _require_admin, _state


@router.get("/admin/stats")
async def dashboard_stats(request: Request):
    _require_admin(request)
    state = _state(request)
    supabase = state.supabase

    catalog = await state.catalog.get_models(include_disabled=True)
    enabled = [m for m in catalog if m.get("enabled", True)]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"{supabase.settings.supabase_url}/rest/v1/ai_requests"
    headers = {
        "apikey": supabase.settings.supabase_service_role_key,
        "Authorization": f"Bearer {supabase.settings.supabase_service_role_key}",
    }
    requests_today = tokens_today = 0
    per_model: dict[str, int] = {}
    recent: list[dict] = []
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                url,
                params={
                    "select": "model,total_tokens,status,created_at,request_id,error_code",
                    "started_at": f"gte.{today}T00:00:00Z",
                    "order": "created_at.desc",
                    "limit": "500",
                },
                headers=headers,
            )
            if response.status_code == 200:
                rows = response.json()
                requests_today = len(rows)
                for row in rows:
                    tokens_today += int(row.get("total_tokens") or 0)
                    model = row.get("model") or "unknown"
                    per_model[model] = per_model.get(model, 0) + 1
                recent = rows[:8]
    except Exception:  # noqa: BLE001 — stats are best-effort
        pass

    by_provider: dict[str, int] = {}
    for m in enabled:
        by_provider[m.get("provider", "nvidia")] = by_provider.get(m.get("provider", "nvidia"), 0) + 1

    top_models = sorted(per_model.items(), key=lambda kv: -kv[1])[:5]
    total_model_requests = sum(per_model.values()) or 1

    return {
        "total_models": len(enabled),
        "disabled_models": len(catalog) - len(enabled),
        "providers": by_provider,
        "requests_today": requests_today,
        "tokens_today": tokens_today,
        "top_models": [
            {"model": m, "requests": n,
             "percentage": round(n * 100 / total_model_requests, 1)}
            for m, n in top_models
        ],
        "recent_requests": [
            {
                "request_id": r.get("request_id"),
                "model": r.get("model"),
                "status": r.get("status"),
                "tokens": r.get("total_tokens"),
                "created_at": r.get("created_at"),
            }
            for r in recent
        ],
    }
