"""Supabase REST access: token verification, profile/plan lookup, usage writes.

Uses only httpx against Supabase's REST surfaces (auth + PostgREST) so Nexa
stays dependency-light and portable. The service-role key never leaves the
server process.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from nexa.config import Settings

logger = logging.getLogger("nexa.supabase")

# Cache verified users for a short window to avoid a REST round-trip per
# request while still respecting token revocation reasonably quickly.
_VERIFY_TTL_SECONDS = 300.0


class SupabaseService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._verify_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # -- auth ---------------------------------------------------------------

    async def verify_access_token(self, token: str) -> dict[str, Any] | None:
        """Verify a Supabase access token; return identity or None.

        Returns a trusted identity dict: user_id, email, account_id.
        Never trusts client-supplied identity fields.
        """
        now = time.monotonic()
        cached = self._verify_cache.get(token)
        if cached is not None:
            expires_at, identity = cached
            if expires_at > now:
                return identity
            del self._verify_cache[token]

        identity = await self._verify_via_rest(token)
        if identity is not None:
            self._verify_cache[token] = (now + _VERIFY_TTL_SECONDS, identity)
            if len(self._verify_cache) > 10_000:
                cutoff = now - _VERIFY_TTL_SECONDS
                self._verify_cache = {
                    k: v for k, v in self._verify_cache.items() if v[0] > cutoff
                }
        return identity

    async def _verify_via_rest(self, token: str) -> dict[str, Any] | None:
        if not self.settings.supabase_configured:
            return None
        url = f"{self.settings.supabase_url}/auth/v1/user"
        headers = {
            "Authorization": f"Bearer {token}",
            "apikey": self.settings.supabase_anon_key,
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url, headers=headers)
            if response.status_code != 200:
                return None
            data = response.json()
        except Exception as exc:  # noqa: BLE001 — auth must fail closed safely
            logger.warning("supabase verify error: %s", type(exc).__name__)
            return None

        user_id = data.get("id")
        if not user_id:
            return None
        return {
            "user_id": user_id,
            "email": data.get("email", ""),
            "account_id": user_id,  # personal accounts: account == user
        }

    # -- plans / profiles -----------------------------------------------------

    async def get_user_plan(self, user_id: str) -> str | None:
        """Read profiles.plan for a user using the service-role key."""
        if not self.settings.usage_persistence_configured:
            return None
        url = f"{self.settings.supabase_url}/rest/v1/profiles"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url,
                    params={"id": f"eq.{user_id}", "select": "plan"},
                    headers=headers,
                )
            if response.status_code != 200:
                return None
            rows = response.json()
            if isinstance(rows, list) and rows:
                plan = rows[0].get("plan")
                return str(plan) if plan else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan lookup failed: %s", type(exc).__name__)
        return None

    # -- usage windows -----------------------------------------------------------

    async def authorize_usage(
        self, *, account_id: str, five_hour_limit: int, daily_limit: int,
        weekly_limit: int, weekly_renewal_count: int, units: int,
        request_id: str,
    ) -> dict | None:
        """Atomic authorize+reserve via PL/pgSQL (row locks). None = RPC failed."""
        url = f"{self.settings.supabase_url}/rest/v1/rpc/ai_authorize_usage"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        payload = {
            "p_account_id": account_id,
            "p_five_hour_limit": five_hour_limit,
            "p_daily_limit": daily_limit,
            "p_weekly_limit": weekly_limit,
            "p_weekly_renewal_count": weekly_renewal_count,
            "p_units": units,
            "p_request_id": request_id,
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("authorize_usage rpc failed: %s", type(exc).__name__)
        return None

    async def finalize_usage(self, request_id: str, actual_units: int) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/rpc/ai_finalize_usage"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    url, json={"p_request_id": request_id,
                               "p_actual_units": max(0, int(actual_units))},
                    headers=headers)
            return response.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("finalize_usage rpc failed: %s", type(exc).__name__)
            return False

    async def release_usage(self, request_id: str) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/rpc/ai_release_usage"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    url, json={"p_request_id": request_id}, headers=headers)
            return response.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("release_usage rpc failed: %s", type(exc).__name__)
            return False

    async def get_usage_state(
        self, account_id: str, five_hour_limit: int, daily_limit: int,
        weekly_limit: int, weekly_renewal_count: int,
    ) -> dict | None:
        """Fetch (and lazily initialize) the account's usage state row."""
        url = f"{self.settings.supabase_url}/rest/v1/rpc/ai_get_usage_state"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(url, json={
                    "p_account_id": account_id,
                    "p_five_hour_limit": five_hour_limit,
                    "p_daily_limit": daily_limit,
                    "p_weekly_limit": weekly_limit,
                    "p_weekly_renewal_count": weekly_renewal_count,
                }, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_usage_state rpc failed: %s", type(exc).__name__)
        return None

    # -- persistence ------------------------------------------------------------

    async def insert_usage(self, table: str, record: dict[str, Any]) -> bool:
        """Best-effort insert into an ai_* table via PostgREST."""
        if not self.settings.usage_persistence_configured:
            return False
        url = f"{self.settings.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Prefer": "return=minimal",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=record, headers=headers)
            return response.status_code in (200, 201, 204)
        except Exception as exc:  # noqa: BLE001
            logger.warning("usage insert failed: %s", type(exc).__name__)
            return False

    async def get_account_limit_overrides(self, account_id: str) -> dict[str, Any] | None:
        if not self.settings.usage_persistence_configured:
            return None
        url = f"{self.settings.supabase_url}/rest/v1/ai_account_limits"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url,
                    params={"account_id": f"eq.{account_id}", "select": "*"},
                    headers=headers,
                )
            if response.status_code != 200:
                return None
            rows = response.json()
            return rows[0] if isinstance(rows, list) and rows else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("limit override lookup failed: %s", type(exc).__name__)
            return None

    # -- gateway API keys (dashboard-managed) ---------------------------------

    @staticmethod
    def hash_key(token: str) -> str:
        import hashlib
        return hashlib.sha256(token.encode()).hexdigest()

    async def find_gateway_key(self, token: str) -> dict | None:
        """Look up a dashboard-created gateway key by hash. Fire-and-forget
        last_used update. Returns {account_id, plan} or None."""
        if not self.settings.usage_persistence_configured:
            return None
        url = f"{self.settings.supabase_url}/rest/v1/ai_gateway_keys"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url,
                    params={
                        "key_hash": f"eq.{self.hash_key(token)}",
                        "enabled": "eq.true",
                        "select": "account_id,plan",
                    },
                    headers=headers,
                )
            if response.status_code == 200:
                rows = response.json()
                if rows:
                    return rows[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("gateway key lookup failed: %s", type(exc).__name__)
        return None

    async def list_gateway_keys(self) -> list[dict]:
        url = f"{self.settings.supabase_url}/rest/v1/ai_gateway_keys"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url,
                    params={"select": "id,name,key_prefix,account_id,plan,enabled,created_at,last_used_at",
                            "order": "created_at.desc"},
                    headers=headers,
                )
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("list gateway keys failed: %s", type(exc).__name__)
        return []

    async def create_gateway_key(self, *, name: str, key_hash: str,
                                 key_prefix: str, account_id: str,
                                 plan: str, created_by: str) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/ai_gateway_keys"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Prefer": "return=minimal",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json={
                    "name": name, "key_hash": key_hash, "key_prefix": key_prefix,
                    "account_id": account_id, "plan": plan, "created_by": created_by,
                }, headers=headers)
            return response.status_code in (200, 201)
        except Exception as exc:  # noqa: BLE001
            logger.warning("create gateway key failed: %s", type(exc).__name__)
            return False

    async def set_gateway_key_enabled(self, key_id: str, enabled: bool) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/ai_gateway_keys"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.patch(
                    url, params={"id": f"eq.{key_id}"},
                    json={"enabled": enabled}, headers=headers)
            return response.status_code in (200, 204)
        except Exception as exc:  # noqa: BLE001
            logger.warning("gateway key update failed: %s", type(exc).__name__)
            return False

    # -- service config (system prompts, routing, agent) -----------------------

    async def get_config(self, key: str) -> dict | None:
        url = f"{self.settings.supabase_url}/rest/v1/ai_service_config"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url, params={"key": f"eq.{key}", "select": "key,value,updated_by,updated_at"},
                    headers=headers)
            if response.status_code == 200:
                rows = response.json()
                return rows[0] if rows else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("config get failed: %s", type(exc).__name__)
        return None

    async def put_config(self, key: str, value: dict, updated_by: str) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/ai_service_config"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json={
                    "key": key, "value": value, "updated_by": updated_by,
                }, headers=headers)
            return response.status_code in (200, 201)
        except Exception as exc:  # noqa: BLE001
            logger.warning("config put failed: %s", type(exc).__name__)
            return False

    # -- accounts: profiles / organizations ------------------------------------

    # -- webhooks ----------------------------------------------------------------

    async def list_webhooks(self) -> list[dict]:
        return await self._get_rows("ai_webhooks",
                                    "id,url,secret,events,enabled,created_at")

    async def create_webhook(self, row: dict) -> bool:
        return await self._insert_row("ai_webhooks", row)

    async def delete_webhook(self, webhook_id: str) -> bool:
        return await self._delete_row("ai_webhooks", "id", webhook_id)

    # -- config backups ------------------------------------------------------------

    async def list_backups(self) -> list[dict]:
        return await self._get_rows("ai_config_backups",
                                    "id,label,created_by,created_at",
                                    order="created_at.desc")

    async def create_backup(self, label: str, payload: dict, created_by: str) -> bool:
        return await self._insert_row("ai_config_backups",
                                      {"label": label, "payload": payload,
                                       "created_by": created_by})

    async def get_backup(self, backup_id: str) -> dict | None:
        rows = await self._get_rows("ai_config_backups", "id,label,payload,created_by,created_at",
                                    filters={"id": f"eq.{backup_id}"})
        return rows[0] if rows else None

    async def delete_backup(self, backup_id: str) -> bool:
        return await self._delete_row("ai_config_backups", "id", backup_id)

    async def _get_rows(self, table: str, select: str, order: str = "",
                        filters: dict | None = None) -> list[dict]:
        url = f"{self.settings.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        params = {"select": select}
        if order:
            params["order"] = order
        params.update(filters or {})
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s query failed: %s", table, type(exc).__name__)
        return []

    async def _insert_row(self, table: str, row: dict) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Prefer": "return=minimal",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=row, headers=headers)
            return response.status_code in (200, 201)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s insert failed: %s", table, type(exc).__name__)
            return False

    async def _delete_row(self, table: str, column: str, value: str) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/{table}"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.delete(
                    url, params={column: f"eq.{value}"}, headers=headers)
            return response.status_code in (200, 204)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s delete failed: %s", table, type(exc).__name__)
            return False

    async def daily_stats(self, days: int = 14) -> list[dict]:
        url = f"{self.settings.supabase_url}/rest/v1/rpc/ai_daily_stats"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    url, json={"p_days": days}, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("daily stats failed: %s", type(exc).__name__)
        return []

    async def list_profiles(self, limit: int = 100) -> list[dict]:
        url = f"{self.settings.supabase_url}/rest/v1/profiles"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url,
                    params={"select": "id,email,plan,created_at", "limit": str(limit),
                            "order": "created_at.desc"},
                    headers=headers,
                )
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("profiles list failed: %s", type(exc).__name__)
        return []

    async def get_account_limit_rows(self) -> list[dict]:
        url = f"{self.settings.supabase_url}/rest/v1/ai_account_limits"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url, params={"select": "*"}, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("account limits list failed: %s", type(exc).__name__)
        return []

    async def upsert_account_limit_row(self, row: dict) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/ai_account_limits"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=row, headers=headers)
            return response.status_code in (200, 201)
        except Exception as exc:  # noqa: BLE001
            logger.warning("account limit upsert failed: %s", type(exc).__name__)
            return False

    async def get_model_catalog_rows(self) -> list[dict[str, Any]]:
        """All admin-managed catalog rows (enabled and disabled)."""
        if not self.settings.usage_persistence_configured:
            return []
        url = f"{self.settings.supabase_url}/rest/v1/ai_model_catalog"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    url,
                    params={"select": "*", "order": "sort_order.asc"},
                    headers=headers,
                )
            if response.status_code == 200 and isinstance(response.json(), list):
                return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("model catalog lookup skipped: %s", type(exc).__name__)
        return []

    async def upsert_model_catalog_row(self, row: dict[str, Any]) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/ai_model_catalog"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=row, headers=headers)
            return response.status_code in (200, 201, 204)
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog upsert failed: %s", type(exc).__name__)
            return False

    async def delete_model_catalog_row(self, model_id: str) -> bool:
        url = f"{self.settings.supabase_url}/rest/v1/ai_model_catalog"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.delete(
                    url, params={"logical_id": f"eq.{model_id}"}, headers=headers)
            return response.status_code in (200, 204)
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog delete failed: %s", type(exc).__name__)
            return False

    async def monthly_tokens_used(self, account_id: str) -> int:
        """Sum of total tokens this calendar month from ai_requests (best effort)."""
        data, _ok = await self.monthly_usage(account_id)
        return int(data.get("total_tokens", 0))

    async def monthly_usage(self, account_id: str) -> tuple[dict[str, int], bool]:
        """Requests + token totals for this calendar month.

        Returns (usage, persistence_ok): persistence_ok is False when the
        RPC/table is missing so callers can surface a configuration warning
        instead of silently showing zeros.
        """
        if not self.settings.usage_persistence_configured:
            return {}, False
        url = f"{self.settings.supabase_url}/rest/v1/rpc/ai_monthly_usage"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    url, json={"p_account_id": account_id}, headers=headers
                )
            if response.status_code == 200 and isinstance(response.json(), dict):
                return response.json(), True
        except Exception as exc:  # noqa: BLE001
            logger.debug("monthly usage lookup skipped: %s", type(exc).__name__)
        return {}, False
