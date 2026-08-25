"""Dynamic model catalog: DB-first (admin-managed) with static fallback.

The admin dashboard writes rows to ai_model_catalog; this service serves
them with a short cache so model changes propagate to clients without
redeploys. When Supabase is unavailable the built-in static catalog keeps
the gateway fully functional.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from nexa.services.supabase import SupabaseService

logger = logging.getLogger("nexa.catalog")

CACHE_TTL_SECONDS = 30.0

# Static fallback — mirrors the 0004 seeds.
FALLBACK_CATALOG: list[dict[str, Any]] = [
    {"id": "stepfun-ai/step-3.7-flash", "display_name": "Step 3.7 Flash",
     "capabilities": ["chat", "code", "streaming", "vision"], "provider": "nvidia",
     "provider_model": "stepfun-ai/step-3.7-flash", "context_window": 65536,
     "max_output_tokens": 8192, "requires_plan": "starter", "enabled": True},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "display_name": "Nemotron 3 Ultra",
     "capabilities": ["chat", "code", "streaming", "tools", "reasoning"], "provider": "nvidia",
     "provider_model": "nvidia/nemotron-3-ultra-550b-a55b", "context_window": 65536,
     "max_output_tokens": 8192, "requires_plan": "plus", "enabled": True},
    {"id": "nvidia/nemotron-3-super-120b-a12b", "display_name": "Nemotron 3 Super",
     "capabilities": ["chat", "code", "streaming", "tools"], "provider": "nvidia",
     "provider_model": "nvidia/nemotron-3-super-120b-a12b", "context_window": 65536,
     "max_output_tokens": 8192, "requires_plan": "plus", "enabled": True},
    {"id": "deepseek-ai/deepseek-v4-flash-0731", "display_name": "DeepSeek V4 Flash",
     "capabilities": ["chat", "code", "streaming"], "provider": "nvidia",
     "provider_model": "deepseek-ai/deepseek-v4-flash-0731", "context_window": 65536,
     "max_output_tokens": 8192, "requires_plan": "starter", "enabled": True},
    {"id": "stealth/ox-alpha", "display_name": "Ox Alpha",
     "capabilities": ["chat", "code", "streaming", "reasoning"], "provider": "openrouter",
     "provider_model": "stealth/ox-alpha", "context_window": 65536,
     "max_output_tokens": 16384, "requires_plan": "starter", "enabled": True},
]


class CatalogService:
    def __init__(self, supabase: SupabaseService) -> None:
        self.supabase = supabase
        self._cache: list[dict[str, Any]] | None = None
        self._cache_at: float = 0.0

    async def get_models(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._cache is None or now - self._cache_at > CACHE_TTL_SECONDS:
            rows = await self.supabase.get_model_catalog_rows()
            if rows:
                self._cache = rows
            elif self._cache is None:
                self._cache = [dict(r) for r in FALLBACK_CATALOG]
            self._cache_at = now
        models = self._cache or []
        if not include_disabled:
            models = [m for m in models if m.get("enabled", True)]
        return models

    async def get(self, model_id: str) -> dict[str, Any] | None:
        for model in await self.get_models():
            if model.get("logical_id") == model_id or model.get("id") == model_id:
                return model
        return None

    def invalidate(self) -> None:
        self._cache = None
        self._cache_at = 0.0

    @staticmethod
    def normalize(row: dict[str, Any]) -> dict[str, Any]:
        """Map a DB row (logical_id keyed) into the public model shape."""
        return {
            "id": row.get("logical_id") or row.get("id", ""),
            "display_name": row.get("display_name") or row.get("id", ""),
            "capabilities": row.get("capabilities") or [],
            "provider": row.get("provider", "nvidia"),
            "context_window": row.get("context_window"),
            "max_output_tokens": row.get("max_output_tokens"),
            "requires_plan": row.get("requires_plan"),
            "enabled": row.get("enabled", True),
        }
