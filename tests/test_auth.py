"""Authentication tests: valid user, invalid token, expired token,
unauthorized account claims."""

from __future__ import annotations

import pytest

from nexa.auth import Authenticator
from nexa.errors import AuthenticationError, AuthorizationError
from tests.conftest import VALID_CHAT_BODY, auth_header


class TestEndpointAuth:
    async def test_missing_token_rejected(self, client):
        response = await client.get("/v1/models")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"

    async def test_invalid_token_rejected(self, client):
        response = await client.get("/v1/models", headers=auth_header("bogus-token"))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"

    async def test_expired_token_rejected(self, client, supabase):
        supabase.add_user("expired")
        del supabase.users["expired"]  # simulates expiry/revocation
        response = await client.get("/v1/models", headers=auth_header("expired"))
        assert response.status_code == 401

    async def test_valid_user_accepted(self, client, supabase):
        supabase.add_user("tok", plan="pro")
        response = await client.get("/v1/models", headers=auth_header("tok"))
        assert response.status_code == 200

    async def test_malformed_header_rejected(self, client):
        response = await client.get("/v1/models", headers={"Authorization": "Basic abc"})
        assert response.status_code == 401


class TestGatewayKeys:
    def make_auth(self, monkeypatch):
        from nexa.config import Settings

        monkeypatch.setenv(
            "NEXA_GATEWAY_KEYS", "nxkey_abcdefghijklmnopqrstuvwxyz:acct1:pro"
        )
        settings = Settings()
        return Authenticator.__new__(Authenticator), settings

    async def test_valid_gateway_key(self):
        from nexa.config import Settings

        settings = Settings(
            gateway_keys_raw=["nxkey_abcdefghijklmnopqrstuvwxyz:acct1:pro"],
            default_plan="starter",
        )
        auth = Authenticator(None, settings.parse_gateway_keys(), settings.default_plan)
        identity = await auth.authenticate_request(
            "Bearer nxkey_abcdefghijklmnopqrstuvwxyz"
        )
        assert identity.account_id == "acct1"
        assert identity.plan == "pro"

    async def test_unknown_gateway_key_rejected(self):
        from nexa.config import Settings

        settings = Settings(
            gateway_keys_raw=["nxkey_abcdefghijklmnopqrstuvwxyz:acct1:pro"]
        )
        auth = Authenticator(None, settings.parse_gateway_keys(), settings.default_plan)
        with pytest.raises(AuthenticationError):
            await auth.authenticate_request("Bearer nxkey_zzzzzzzzzzzzzzzzzz")


class TestAccountClaims:
    async def test_account_mismatch_rejected(self, client, supabase):
        supabase.add_user("tok", user_id="u-1")
        body = {**VALID_CHAT_BODY, "account_id": "someone-else"}
        response = await client.post(
            "/v1/chat/completions", json=body, headers=auth_header("tok")
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AUTHORIZATION_FAILED"

    async def test_matching_account_ok(self, client, supabase, nvidia):
        supabase.add_user("tok", user_id="u-1", plan="pro")
        body = {**VALID_CHAT_BODY, "account_id": "u-1"}
        response = await client.post(
            "/v1/chat/completions", json=body, headers=auth_header("tok")
        )
        assert response.status_code == 200
