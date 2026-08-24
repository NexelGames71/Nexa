"""Nexa application factory.

Portable ASGI app: runs under uvicorn (Docker/Cloud Run/VPS) and can be
mounted by Vercel's Python runtime. No Vercel-specific APIs are used.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nexa.api import agent, chat, health, models
from nexa.api import usage as usage_api
from nexa.appstate import NexaState
from nexa.auth import Authenticator
from nexa.config import Settings, get_settings
from nexa.context import RequestContext, configure_logging, log_request, new_request_id
from nexa.errors import INTERNAL_ERROR, NexaError
from nexa.policies.concurrency import ConcurrencyManager
from nexa.policies.service import PolicyService
from nexa.providers.nvidia import NVIDIAProvider
from nexa.routing.catalog import catalog_payload  # noqa: F401
from nexa.services.supabase import SupabaseService
from nexa.services.usage import UsageTracker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    supabase = SupabaseService(settings)
    authenticator = Authenticator(
        supabase=supabase,
        gateway_keys=settings.parse_gateway_keys(),
        default_plan=settings.default_plan,
    )
    policies = PolicyService(settings, supabase)
    concurrency = ConcurrencyManager()
    nvidia = NVIDIAProvider(settings)
    usage = UsageTracker(supabase)

    state = NexaState(
        settings=settings,
        authenticator=authenticator,
        policies=policies,
        usage=usage,
        supabase=supabase,
        concurrency=concurrency,
        providers={nvidia.name: nvidia},
    )

    app = FastAPI(
        title="Nexa AI Gateway",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.nexa = state

    # CORS: trusted Nexcoder origins only; never wildcard in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins or (
            ["*"] if not settings.is_production else []
        ),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-Id", "Retry-After"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        ctx = RequestContext(
            request_id=new_request_id(),
            method=request.method,
            path=request.url.path,
        )
        request.state.nexa_ctx = ctx
        started = time.monotonic()
        try:
            response = await call_next(request)
        except NexaError as exc:
            response = JSONResponse(exc.to_payload(), status_code=exc.http_status)
            if getattr(exc, "headers", None):
                response.headers.update(exc.headers)
        except Exception as exc:  # noqa: BLE001 — never leak internals
            logger.exception("unhandled error request_id=%s", ctx.request_id)
            safe = NexaError(INTERNAL_ERROR, "Internal error", internal=type(exc).__name__)
            response = JSONResponse(safe.to_payload(), status_code=safe.http_status)

        response.headers["X-Request-Id"] = ctx.request_id
        # Secure headers
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response

    # Structured access log + usage-safe error normalization.
    @app.middleware("http")
    async def logging_middleware(request: Request, call_next):
        response = await call_next(request)
        ctx: RequestContext | None = getattr(request.state, "nexa_ctx", None)
        if ctx is not None and request.url.path != "/v1/health":
            log_request(ctx, str(response.status_code))
        return response

    @app.exception_handler(NexaError)
    async def nexa_error_handler(request: Request, exc: NexaError):
        response = JSONResponse(exc.to_payload(), status_code=exc.http_status)
        headers = getattr(exc, "headers", {})
        if headers:
            response.headers.update(headers)
        return response

    app.include_router(health.router, prefix="/v1")
    app.include_router(models.router, prefix="/v1")
    app.include_router(chat.router, prefix="/v1")
    app.include_router(agent.router, prefix="/v1")
    app.include_router(usage_api.router, prefix="/v1")

    @app.get("/")
    async def root() -> dict:
        return {"service": "nexa", "status": "ok"}

    return app


app = create_app()
