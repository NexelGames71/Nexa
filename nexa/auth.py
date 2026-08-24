"""Authentication middleware: authenticateRequest().

Every protected request must present a trusted credential:

1. Supabase access token (verified against the project's auth server).
2. Static gateway key (``nxkey_...``) mapped to (account_id, plan) via config.

Client-provided user/account IDs are never used as authentication.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nexa.context import RequestContext
from nexa.errors import AuthenticationError, AuthorizationError
from nexa.services.supabase import SupabaseService

_GATEWAY_KEY_RE = re.compile(r"^nxkey_[A-Za-z0-9_-]{16,}$")


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    account_id: str
    plan: str
    email: str = ""
    auth_method: str = "supabase"  # or "gateway_key"


class Authenticator:
    def __init__(self, supabase: SupabaseService, gateway_keys: dict[str, tuple[str, str]], default_plan: str) -> None:
        self._supabase = supabase
        self._gateway_keys = gateway_keys
        self._default_plan = default_plan

    async def authenticate_request(self, authorization_header: str | None) -> AuthIdentity:
        if not authorization_header:
            raise AuthenticationError("Missing Authorization header")

        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("Invalid Authorization header; expected Bearer token")
        token = token.strip()

        if _GATEWAY_KEY_RE.match(token):
            return await self._authenticate_gateway_key(token)
        return await self._authenticate_supabase(token)

    async def _authenticate_gateway_key(self, token: str) -> AuthIdentity:
        mapping = self._gateway_keys.get(token)
        if mapping is None:
            raise AuthenticationError("Invalid API key")
        account_id, plan = mapping
        return AuthIdentity(
            user_id=account_id,
            account_id=account_id,
            plan=plan,
            auth_method="gateway_key",
        )

    async def _authenticate_supabase(self, token: str) -> AuthIdentity:
        identity = await self._supabase.verify_access_token(token)
        if identity is None:
            raise AuthenticationError("Invalid or expired token")
        plan = await self._supabase.get_user_plan(identity["user_id"]) or self._default_plan
        return AuthIdentity(
            user_id=identity["user_id"],
            account_id=identity.get("account_id") or identity["user_id"],
            plan=plan,
            email=identity.get("email", ""),
            auth_method="supabase",
        )


def apply_identity(ctx: RequestContext, identity: AuthIdentity) -> None:
    ctx.user_id = identity.user_id
    ctx.account_id = identity.account_id
    ctx.plan = identity.plan


def require_model_permission(allowed_models: set[str], requested: str) -> None:
    if requested not in allowed_models:
        raise AuthorizationError(f"Model '{requested}' is not available on your plan")


def ensure_account_match(identity: AuthIdentity, claimed_account_id: str | None) -> None:
    """Reject requests where a client body claims a different account."""
    if claimed_account_id and claimed_account_id != identity.account_id:
        raise AuthorizationError("Account mismatch")
