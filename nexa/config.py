"""Centralized, typed configuration. All secrets are read server-side only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_routes(raw: str) -> dict[str, str]:
    routes: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        logical, provider_model = pair.split("=", 1)
        logical, provider_model = logical.strip(), provider_model.strip()
        if logical and provider_model:
            routes[logical] = provider_model
    return routes


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: os.getenv("NEXA_ENV", "development"))
    base_url: str = field(default_factory=lambda: os.getenv("NEXA_BASE_URL", "http://127.0.0.1:8000"))

    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_anon_key: str = field(default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", ""))
    supabase_service_role_key: str = field(
        default_factory=lambda: os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    )
    supabase_jwt_secret: str = field(default_factory=lambda: os.getenv("SUPABASE_JWT_SECRET", ""))

    nvidia_api_key: str = field(default_factory=lambda: os.getenv("NVIDIA_API_KEY", ""))
    nvidia_base_url: str = field(
        default_factory=lambda: os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    )
    nvidia_default_model: str = field(
        default_factory=lambda: os.getenv("NVIDIA_DEFAULT_MODEL", "")
    )

    model_routes: dict[str, str] = field(
        default_factory=lambda: _parse_routes(os.getenv("NEXA_MODEL_ROUTES", ""))
    )
    gateway_keys_raw: list[str] = field(default_factory=lambda: _env_list("NEXA_GATEWAY_KEYS"))
    default_plan: str = field(default_factory=lambda: os.getenv("NEXA_DEFAULT_PLAN", "starter"))

    allowed_origins: list[str] = field(default_factory=lambda: _env_list("NEXA_ALLOWED_ORIGINS"))

    upstream_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("NEXA_UPSTREAM_TIMEOUT_SECONDS", "120"))
    )
    stream_idle_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("NEXA_STREAM_IDLE_TIMEOUT_SECONDS", "60"))
    )

    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def usage_persistence_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    def parse_gateway_keys(self) -> dict[str, tuple[str, str]]:
        """Parse NEXA_GATEWAY_KEYS triples into {token: (account_id, plan)}."""
        keys: dict[str, tuple[str, str]] = {}
        for entry in self.gateway_keys_raw:
            parts = entry.split(":")
            if len(parts) < 3:
                continue
            token, account_id, plan = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if token and account_id and plan:
                keys[token] = (account_id, plan)
        return keys

    def resolve_provider_model(self, logical_model: str) -> str | None:
        return self.model_routes.get(logical_model) or self.nvidia_default_model or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
