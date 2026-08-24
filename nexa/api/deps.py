"""Shared FastAPI dependencies: app state, authentication, request context."""

from __future__ import annotations

from fastapi import Depends, Request

from nexa.appstate import NexaState
from nexa.auth import AuthIdentity, Authenticator
from nexa.context import RequestContext


def get_nexa_state(request: Request) -> NexaState:
    return request.app.state.nexa


def get_authenticator(state: NexaState = Depends(get_nexa_state)) -> Authenticator:
    return state.authenticator


async def current_identity(
    request: Request,
    authenticator: Authenticator = Depends(get_authenticator),
) -> AuthIdentity:
    identity = await authenticator.authenticate_request(request.headers.get("authorization"))
    ctx: RequestContext | None = getattr(request.state, "nexa_ctx", None)
    if ctx is not None:
        ctx.user_id = identity.user_id
        ctx.account_id = identity.account_id
        ctx.plan = identity.plan
    return identity


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
