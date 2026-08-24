"""Usage tracking: structured log always; DB write when configured.

Records metadata only — never prompts or responses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from nexa.context import RequestContext
from nexa.providers.base import Usage
from nexa.services.supabase import SupabaseService

logger = logging.getLogger("nexa.usage")


@dataclass
class UsageRecord:
    request_id: str
    user_id: str | None = None
    account_id: str | None = None
    provider: str | None = None
    model: str | None = None
    started_at: float = field(default_factory=lambda: time.time())
    completed_at: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    status: Literal["success", "error", "cancelled"] = "success"
    error_code: str | None = None

    def to_row(self) -> dict[str, Any]:
        from datetime import datetime, timezone

        def iso(ts: float) -> str:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        row = {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "account_id": self.account_id,
            "provider": self.provider,
            "model": self.model,
            "started_at": iso(self.started_at),
            "completed_at": iso(self.completed_at or time.time()),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_code": self.error_code,
        }
        return {k: v for k, v in row.items() if v is not None}


class UsageTracker:
    def __init__(self, supabase: SupabaseService) -> None:
        self._supabase = supabase

    async def record(
        self,
        ctx: RequestContext,
        *,
        usage: Usage | None = None,
        status: Literal["success", "error", "cancelled"] = "success",
        error_code: str | None = None,
    ) -> UsageRecord:
        record = UsageRecord(
            request_id=ctx.request_id,
            user_id=ctx.user_id,
            account_id=ctx.account_id,
            provider=ctx.provider,
            model=ctx.model,
            started_at=time.time() - ctx.latency_ms / 1000,
            completed_at=time.time(),
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            latency_ms=ctx.latency_ms,
            status=status,
            error_code=error_code,
        )
        # Structured log (no content, no secrets).
        logger.info(
            "usage %s",
            {
                "request_id": record.request_id,
                "user_id": record.user_id,
                "account_id": record.account_id,
                "provider": record.provider,
                "model": record.model,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.total_tokens,
                "latency_ms": record.latency_ms,
                "status": record.status,
                "error_code": record.error_code,
            },
        )
        # Best-effort persistence.
        await self._supabase.insert_usage("ai_requests", record.to_row())
        return record
