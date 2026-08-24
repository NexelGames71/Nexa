"""Normalized Nexa errors.

Clients always receive stable Nexa error codes; raw provider errors and
internal details never cross the boundary.
"""

from __future__ import annotations

from typing import Any

# Stable error codes (spec §18).
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
INVALID_REQUEST = "INVALID_REQUEST"
AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
RATE_LIMITED = "RATE_LIMITED"
CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
USAGE_LIMIT = "USAGE_LIMIT"
FIVE_HOUR_LIMIT_REACHED = "FIVE_HOUR_LIMIT_REACHED"
DAILY_LIMIT_REACHED = "DAILY_LIMIT_REACHED"
WEEKLY_LIMIT_REACHED = "WEEKLY_LIMIT_REACHED"
REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
CLIENT_CANCELLED = "CLIENT_CANCELLED"
INTERNAL_ERROR = "INTERNAL_ERROR"

_HTTP_STATUS: dict[str, int] = {
    PROVIDER_UNAVAILABLE: 502,
    PROVIDER_RATE_LIMIT: 429,
    MODEL_UNAVAILABLE: 404,
    INVALID_REQUEST: 400,
    AUTHENTICATION_FAILED: 401,
    AUTHORIZATION_FAILED: 403,
    RATE_LIMITED: 429,
    CONCURRENCY_LIMIT: 429,
    USAGE_LIMIT: 402,
    FIVE_HOUR_LIMIT_REACHED: 429,
    DAILY_LIMIT_REACHED: 429,
    WEEKLY_LIMIT_REACHED: 429,
    REQUEST_TIMEOUT: 504,
    CLIENT_CANCELLED: 499,
    INTERNAL_ERROR: 500,
}


class NexaError(Exception):
    """Base error carrying a stable code and safe, client-facing message."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
        internal: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status or _HTTP_STATUS.get(code, 500)
        self.details = details or {}
        # Internal context for logs only; never returned to clients.
        self.internal = internal

    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return {"error": body}


class InvalidRequestError(NexaError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(INVALID_REQUEST, message, **kwargs)


class AuthenticationError(NexaError):
    def __init__(self, message: str = "Authentication required", **kwargs: Any) -> None:
        super().__init__(AUTHENTICATION_FAILED, message, **kwargs)


class AuthorizationError(NexaError):
    def __init__(self, message: str = "Not authorized for this resource", **kwargs: Any) -> None:
        super().__init__(AUTHORIZATION_FAILED, message, **kwargs)


class RateLimitedError(NexaError):
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after_seconds: int | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        super().__init__(RATE_LIMITED, message, details=details, **kwargs)
        if retry_after_seconds is not None:
            self.headers = {"Retry-After": str(max(1, int(retry_after_seconds)))}
        else:
            self.headers = {}


class ConcurrencyLimitError(NexaError):
    def __init__(self, message: str = "Too many concurrent generations", **kwargs: Any) -> None:
        super().__init__(CONCURRENCY_LIMIT, message, **kwargs)


class UsageLimitError(NexaError):
    def __init__(self, message: str = "Usage limit reached for current plan", **kwargs: Any) -> None:
        super().__init__(USAGE_LIMIT, message, **kwargs)


class ProviderError(NexaError):
    pass


class RequestTimeoutError(NexaError):
    def __init__(self, message: str = "Upstream request timed out", **kwargs: Any) -> None:
        super().__init__(REQUEST_TIMEOUT, message, **kwargs)
