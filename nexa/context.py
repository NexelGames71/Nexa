"""Per-request identity context: request IDs and structured logging."""

from __future__ import annotations

import logging
import secrets
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from nexa.errors import NexaError

logger = logging.getLogger("nexa")


def new_request_id() -> str:
    return f"nexa_req_{secrets.token_hex(10)}"


@dataclass
class RequestContext:
    request_id: str
    method: str
    path: str
    user_id: str | None = None
    account_id: str | None = None
    plan: str | None = None
    model: str | None = None
    provider: str | None = None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def latency_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)

    def log_fields(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "method": self.method,
            "path": self.path,
            "user_id": self.user_id,
            "account_id": self.account_id,
            "plan": self.plan,
            "model": self.model,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
        }


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def log_request(ctx: RequestContext, status: str, *, error: NexaError | None = None) -> None:
    fields = ctx.log_fields()
    fields["status"] = status
    if error is not None:
        fields["error_code"] = error.code
        if error.internal:
            fields["error_internal"] = error.internal
    logger.info("request %s", fields)
