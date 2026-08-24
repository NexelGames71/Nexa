"""GET /v1/health — service health. No secrets, no infra details."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    state = request.app.state.nexa
    return {
        "status": "ok",
        "service": "nexa",
        "version": state.version,
        "providers": {
            name: {"configured": bool(getattr(p, "configured", True))}
            for name, p in state.providers.items()
        },
    }
