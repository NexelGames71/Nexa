"""Concurrency control for simultaneous generations.

acquire_generation_slot() / release_generation_slot(). Slots are always
released on completion, failure, cancellation, provider error and timeout —
the chat route wraps the whole generation in a try/finally.
"""

from __future__ import annotations

from nexa.errors import ConcurrencyLimitError


class ConcurrencyManager:
    def __init__(self) -> None:
        from nexa.policies.ratelimit import MemoryCounterStore

        self._store = MemoryCounterStore()

    def acquire_generation_slot(self, key: str, cap: int) -> None:
        """Raise CONCURRENCY_LIMIT if the caller is at cap."""
        if cap <= 0:
            raise ConcurrencyLimitError("Concurrent generations disabled")
        if not self._store.increment_if_below(f"conc:{key}", cap):
            raise ConcurrencyLimitError(
                "Too many concurrent generations; wait for one to finish"
            )

    def release_generation_slot(self, key: str) -> None:
        self._store.decrement(f"conc:{key}")

    def active(self, key: str) -> int:
        return self._store.get(f"conc:{key}")
