"""Usage windows: fast 5-hour allowance + slow 7-day allowance with one
complimentary weekly renewal.

Terminology (authoritative):
  five_hour_window / five_hour_usage   — resets 5h after first use
  weekly_cycle / weekly_usage          — resets 7 days after first use
  weekly_renewal                       — one complimentary restore per cycle

Every limited AI request passes through UsageService.authorize() which
lazily expires windows, grants the renewal atomically when eligible, and
reserves units before the provider call. finalize()/release() reconcile
after the request. Idempotent per request_id.

Persistence: atomic PL/pgSQL RPC (row locks) when Supabase is configured —
safe across serverless instances — with an in-memory fallback for local
runs and tests (single process only).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from nexa.policies.plans import PlanPolicy
from nexa.services.supabase import SupabaseService

logger = logging.getLogger("nexa.usage_windows")

FIVE_HOUR_SECONDS = 5 * 3600
DAILY_SECONDS = 24 * 3600
WEEK_SECONDS = 7 * 24 * 3600


@dataclass
class WindowDecision:
    allowed: bool
    window: str | None = None          # "five_hour" | "weekly" when blocked
    reset_at: float | None = None      # epoch seconds when the window resets
    renewal_granted: bool = False
    retry_after_seconds: int = 0


@dataclass
class _MemoryState:
    usage_started_at: float | None = None
    five_hour_used: int = 0
    five_hour_window_started_at: float | None = None
    five_hour_window_ends_at: float | None = None
    daily_used: int = 0
    daily_window_started_at: float | None = None
    daily_window_ends_at: float | None = None
    weekly_used: int = 0
    weekly_cycle_started_at: float | None = None
    weekly_cycle_ends_at: float | None = None
    weekly_renewals_used: int = 0
    reservations: dict = field(default_factory=dict)  # request_id -> units


class UsageService:
    def __init__(self, supabase: SupabaseService) -> None:
        self.supabase = supabase
        self._memory: dict[str, _MemoryState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # -- public API ---------------------------------------------------------

    async def authorize(
        self, account_id: str, policy: PlanPolicy, units: int, request_id: str
    ) -> WindowDecision:
        units = max(1, int(units))
        if self.supabase.settings.usage_persistence_configured:
            return await self._authorize_db(
                account_id, policy, units, request_id)
        return await self._authorize_memory(
            account_id, policy, units, request_id)

    async def finalize(self, account_id: str, request_id: str,
                       actual_units: int) -> None:
        """Reconcile a reservation with the provider's real usage."""
        if self.supabase.settings.usage_persistence_configured:
            await self.supabase.finalize_usage(request_id, max(0, int(actual_units)))
            return
        async with self._account_lock(account_id):
            state = self._memory.get(account_id)
            if not state or request_id not in state.reservations:
                return
            reserved = state.reservations.pop(request_id)
            delta = max(0, int(actual_units)) - reserved
            state.five_hour_used = max(0, state.five_hour_used + delta)
            state.daily_used = max(0, state.daily_used + delta)
            state.weekly_used = max(0, state.weekly_used + delta)

    async def release(self, account_id: str, request_id: str) -> None:
        """Give back reserved units after an infrastructure failure."""
        if self.supabase.settings.usage_persistence_configured:
            await self.supabase.release_usage(request_id)
            return
        async with self._account_lock(account_id):
            state = self._memory.get(account_id)
            if not state or request_id not in state.reservations:
                return
            reserved = state.reservations.pop(request_id)
            state.five_hour_used = max(0, state.five_hour_used - reserved)
            state.daily_used = max(0, state.daily_used - reserved)
            state.weekly_used = max(0, state.weekly_used - reserved)

    async def snapshot(self, account_id: str, policy: PlanPolicy) -> dict:
        """Server-authoritative window state for GET /v1/usage."""
        if self.supabase.settings.usage_persistence_configured:
            state = await self.supabase.get_usage_state(
                account_id, policy.five_hour_limit, policy.weekly_limit,
                policy.weekly_renewal_count)
        else:
            async with self._account_lock(account_id):
                state = self._memory_state(
                    account_id, policy).__dict__.copy()
                state.pop("reservations", None)
        return self._shape_snapshot(state or {}, policy)

    # -- memory implementation ------------------------------------------------

    def _account_lock(self, account_id: str) -> asyncio.Lock:
        return self._locks.setdefault(account_id, asyncio.Lock())

    def _memory_state(self, account_id: str, policy: PlanPolicy) -> _MemoryState:
        return self._memory.setdefault(account_id, _MemoryState())

    async def _authorize_memory(
        self, account_id: str, policy: PlanPolicy, units: int, request_id: str
    ) -> WindowDecision:
        async with self._account_lock(account_id):
            state = self._memory_state(account_id, policy)
            now = time.time()
            renewal_granted = False

            if request_id in state.reservations:
                return WindowDecision(allowed=True)  # idempotent retry

            # First successful request starts all clocks (spec §8).
            if state.usage_started_at is None:
                state.usage_started_at = now
                state.five_hour_window_started_at = now
                state.five_hour_window_ends_at = now + FIVE_HOUR_SECONDS
                state.daily_window_started_at = now
                state.daily_window_ends_at = now + DAILY_SECONDS
                state.weekly_cycle_started_at = now
                state.weekly_cycle_ends_at = now + WEEK_SECONDS

            # Lazy five-hour reset (spec §16).
            if state.five_hour_window_ends_at is not None and now >= state.five_hour_window_ends_at:
                state.five_hour_used = 0
                state.five_hour_window_started_at = now
                state.five_hour_window_ends_at = now + FIVE_HOUR_SECONDS

            # Lazy daily reset.
            if state.daily_window_ends_at is not None and now >= state.daily_window_ends_at:
                state.daily_used = 0
                state.daily_window_started_at = now
                state.daily_window_ends_at = now + DAILY_SECONDS

            # Lazy weekly reset (spec §17).
            if state.weekly_cycle_ends_at is not None and now >= state.weekly_cycle_ends_at:
                state.weekly_used = 0
                state.weekly_renewals_used = 0
                state.weekly_cycle_started_at = now
                state.weekly_cycle_ends_at = now + WEEK_SECONDS

            if state.five_hour_used + units > policy.five_hour_limit:
                reset_at = state.five_hour_window_ends_at or now
                return WindowDecision(
                    allowed=False, window="five_hour", reset_at=reset_at,
                    retry_after_seconds=max(1, int(reset_at - now)))

            if state.daily_used + units > policy.daily_limit:
                reset_at = state.daily_window_ends_at or now
                return WindowDecision(
                    allowed=False, window="daily", reset_at=reset_at,
                    retry_after_seconds=max(1, int(reset_at - now)))

            if state.weekly_used + units > policy.weekly_limit:
                # Complimentary renewal: exactly one per weekly cycle,
                # granted atomically inside this locked section (spec §6).
                if state.weekly_renewals_used < policy.weekly_renewal_count:
                    state.weekly_renewals_used += 1
                    state.weekly_used = 0
                    renewal_granted = True
                    logger.info("weekly renewal granted account=%s cycle_started=%s",
                                account_id, state.weekly_cycle_started_at)
                else:
                    reset_at = state.weekly_cycle_ends_at or now
                    return WindowDecision(
                        allowed=False, window="weekly", reset_at=reset_at,
                        retry_after_seconds=max(1, int(reset_at - now)))

            state.five_hour_used += units
            state.daily_used += units
            state.weekly_used += units
            state.reservations[request_id] = units
            return WindowDecision(allowed=True, renewal_granted=renewal_granted)

    # -- Supabase atomic implementation ---------------------------------------

    async def _authorize_db(
        self, account_id: str, policy: PlanPolicy, units: int, request_id: str
    ) -> WindowDecision:
        result = await self.supabase.authorize_usage(
            account_id=account_id,
            five_hour_limit=policy.five_hour_limit,
            daily_limit=policy.daily_limit,
            weekly_limit=policy.weekly_limit,
            weekly_renewal_count=policy.weekly_renewal_count,
            units=units,
            request_id=request_id,
        )
        if result is None:
            # Persistence hiccup: fail open to the in-memory path so the
            # gateway stays available (single-instance enforcement only).
            logger.warning("usage rpc unavailable; falling back to memory")
            return await self._authorize_memory(
                account_id, policy, units, request_id)
        if result.get("allowed"):
            return WindowDecision(allowed=True,
                                  renewal_granted=bool(result.get("renewal_granted")))
        reset_at = result.get("reset_at")
        reset_ts = time.time()
        if reset_at:
            try:
                from datetime import datetime
                reset_ts = datetime.fromisoformat(reset_at.replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
        return WindowDecision(
            allowed=False, window=result.get("window") or "weekly",
            reset_at=reset_ts,
            retry_after_seconds=max(1, int(reset_ts - time.time())))

    # -- shaping ----------------------------------------------------------------

    def _shape_snapshot(self, state: dict, policy: PlanPolicy) -> dict:
        now = time.time()
        five_limit = policy.five_hour_limit
        weekly_limit = policy.weekly_limit

        five_used = int(state.get("five_hour_used", 0))
        five_ends = state.get("five_hour_window_ends_at")
        five_ends_ts = _to_ts(five_ends)
        started = state.get("usage_started_at") is not None
        if not started:
            five_ends_ts = None
        if started and five_ends_ts and now >= five_ends_ts:
            # Lazily expired since the last request: show the reset state.
            five_used = 0
            five_ends_ts = None

        daily_used = int(state.get("daily_used", 0))
        daily_ends_ts = _to_ts(state.get("daily_window_ends_at"))
        if started and daily_ends_ts and now >= daily_ends_ts:
            daily_used = 0
            daily_ends_ts = None

        weekly_used = int(state.get("weekly_used", 0))
        cycle_ends_ts = _to_ts(state.get("weekly_cycle_ends_at"))
        if started and cycle_ends_ts and now >= cycle_ends_ts:
            weekly_used = 0
            cycle_ends_ts = None
        renewals_used = int(state.get("weekly_renewals_used", 0))
        renewal_available = (not started) or renewals_used < policy.weekly_renewal_count

        def pct(used: int, limit: int) -> int:
            if limit <= 0 or used >= limit:
                return 0
            return round(max(0, (limit - used)) * 100 / limit)

        return {
            "usage_started": started,
            "five_hour": {
                "limit": five_limit,
                "used": five_used,
                "remaining": max(0, five_limit - five_used),
                "percentage_remaining": pct(five_used, five_limit),
                "window_started_at": _iso(state.get("five_hour_window_started_at")),
                "window_ends_at": _iso(five_ends_ts) if five_ends_ts else None,
                "reset_in_seconds": max(0, int(five_ends_ts - now)) if five_ends_ts else None,
            },
            "daily": {
                "limit": policy.daily_limit,
                "used": daily_used,
                "remaining": max(0, policy.daily_limit - daily_used),
                "percentage_remaining": pct(daily_used, policy.daily_limit),
                "window_started_at": _iso(state.get("daily_window_started_at")),
                "window_ends_at": _iso(daily_ends_ts) if daily_ends_ts else None,
                "reset_in_seconds": max(0, int(daily_ends_ts - now)) if daily_ends_ts else None,
            },
            "weekly": {
                "limit": weekly_limit,
                "used": weekly_used,
                "remaining": max(0, weekly_limit - weekly_used),
                "percentage_remaining": pct(weekly_used, weekly_limit),
                "cycle_started_at": _iso(state.get("weekly_cycle_started_at")),
                "cycle_ends_at": _iso(cycle_ends_ts) if cycle_ends_ts else None,
                "reset_in_seconds": max(0, int(cycle_ends_ts - now)) if cycle_ends_ts else None,
                "renewal_available": renewal_available,
                "renewal_used": started and not renewal_available,
                "renewals_used": renewals_used,
                "renewal_count": policy.weekly_renewal_count,
            },
        }


def _to_ts(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _iso(ts) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    return str(ts)

