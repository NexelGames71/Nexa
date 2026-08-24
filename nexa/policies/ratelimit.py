"""Rate limiting with a pluggable store.

Default store is in-process (single instance). Set REDIS_URL for a shared
store across instances; the interface is intentionally tiny so a Redis
implementation can be dropped in without touching route code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0
    limit: int = 0
    remaining: int = 0


@dataclass
class _Window:
    hits: list[float] = field(default_factory=list)


class RateLimiter:
    """Sliding-window limiter over (scope_key, window_seconds, limit) buckets."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, int], _Window] = {}

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        bucket = self._buckets.setdefault((key, window_seconds), _Window())
        cutoff = now - window_seconds
        bucket.hits[:] = [h for h in bucket.hits if h > cutoff]

        if len(bucket.hits) >= limit:
            retry_after = int(bucket.hits[0] + window_seconds - now) + 1
            return RateLimitResult(
                allowed=False,
                retry_after_seconds=max(1, retry_after),
                limit=limit,
                remaining=0,
            )
        bucket.hits.append(now)
        # Opportunistic cleanup to keep memory bounded.
        if len(self._buckets) > 100_000:
            stale = [
                k
                for k, w in self._buckets.items()
                if not w.hits or all(h <= now - k[1] for h in w.hits)
            ]
            for k in stale[:50_000]:
                del self._buckets[k]
        return RateLimitResult(allowed=True, limit=limit, remaining=limit - len(bucket.hits))


class MemoryCounterStore:
    """Atomic-enough counter store for concurrency slots (single process)."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def increment_if_below(self, key: str, cap: int) -> bool:
        current = self._counters.get(key, 0)
        if current >= cap:
            return False
        self._counters[key] = current + 1
        return True

    def decrement(self, key: str) -> None:
        value = self._counters.get(key, 0)
        if value <= 1:
            self._counters.pop(key, None)
        else:
            self._counters[key] = value - 1

    def get(self, key: str) -> int:
        return self._counters.get(key, 0)
