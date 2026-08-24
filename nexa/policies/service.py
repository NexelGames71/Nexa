"""Policy service: single entry point combining plan policy, rate limits,
concurrency and usage checks. Routes depend on this facade only."""

from __future__ import annotations

import time
from dataclasses import dataclass

from nexa.auth import AuthIdentity
from nexa.config import Settings
from nexa.errors import InvalidRequestError, RateLimitedError, UsageLimitError
from nexa.policies.concurrency import ConcurrencyManager
from nexa.policies.plans import PlanPolicy, get_plan_policy
from nexa.policies.ratelimit import RateLimiter
from nexa.services.supabase import SupabaseService


@dataclass(frozen=True)
class LimitOverrides:
    requests_per_minute: int | None = None
    requests_per_hour: int | None = None
    concurrent_generations: int | None = None
    monthly_token_limit: int | None = None


class PolicyService:
    def __init__(self, settings: Settings, supabase: SupabaseService) -> None:
        self.settings = settings
        self.supabase = supabase
        self.rate_limiter = RateLimiter()
        self.concurrency = ConcurrencyManager()
        self._overrides_cache: dict[str, tuple[float, LimitOverrides]] = {}

    def plan_policy(self, identity: AuthIdentity) -> PlanPolicy:
        return get_plan_policy(identity.plan)

    async def _overrides(self, account_id: str) -> LimitOverrides:
        cached = self._overrides_cache.get(account_id)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        row = await self.supabase.get_account_limit_overrides(account_id)
        overrides = LimitOverrides(
            requests_per_minute=row.get("requests_per_minute") if row else None,
            requests_per_hour=row.get("requests_per_hour") if row else None,
            concurrent_generations=row.get("concurrent_generations") if row else None,
            monthly_token_limit=row.get("monthly_token_limit") if row else None,
        )
        self._overrides_cache[account_id] = (now + 60.0, overrides)
        return overrides

    async def enforce_rate_limits(
        self, identity: AuthIdentity, client_ip: str | None
    ) -> PlanPolicy:
        """Check per-minute / per-hour / IP limits. Raises RateLimitedError."""
        policy = self.plan_policy(identity)
        overrides = await self._overrides(identity.account_id)
        rpm = overrides.requests_per_minute or policy.requests_per_minute
        rph = overrides.requests_per_hour or policy.requests_per_hour

        minute = self.rate_limiter.check(f"user:{identity.user_id}:m", limit=rpm, window_seconds=60)
        if not minute.allowed:
            raise RateLimitedError(
                "Requests-per-minute limit reached",
                retry_after_seconds=minute.retry_after_seconds,
            )
        hour = self.rate_limiter.check(f"user:{identity.user_id}:h", limit=rph, window_seconds=3600)
        if not hour.allowed:
            raise RateLimitedError(
                "Requests-per-hour limit reached",
                retry_after_seconds=hour.retry_after_seconds,
            )
        if client_ip:
            ip = self.rate_limiter.check(f"ip:{client_ip}:m", limit=max(rpm * 4, 60), window_seconds=60)
            if not ip.allowed:
                raise RateLimitedError(
                    "Too many requests from this network",
                    retry_after_seconds=ip.retry_after_seconds,
                )
        return policy

    def check_model_allowed(self, identity: AuthIdentity, logical_model: str) -> None:
        policy = self.plan_policy(identity)
        if logical_model not in policy.allowed_models:
            raise UsageLimitError(
                f"Model '{logical_model}' requires a higher plan",
                details={"required_upgrade": True, "plan": identity.plan},
            )

    def validate_context_size(self, identity: AuthIdentity, messages: list[dict]) -> None:
        """Guard against pathological payloads only.

        The client owns context compaction (it knows the real model window);
        a strict plan-level rejection here breaks legitimate agent runs whose
        history the client already compacted. We only block payloads so large
        that they cannot plausibly fit any catalog model.
        """
        total_chars = sum(
            len(str(m.get("content", ""))) for m in messages
        )
        estimated_tokens = total_chars // 3
        hard_ceiling = 180_000  # ~540k chars; far beyond every catalog model
        if estimated_tokens > hard_ceiling:
            raise InvalidRequestError(
                "Context exceeds the maximum supported request size",
                details={"maximum_context": hard_ceiling},
            )

    async def enforce_monthly_tokens(self, identity: AuthIdentity, policy: PlanPolicy) -> int:
        """Return remaining monthly tokens; raises UsageLimitError when exhausted."""
        overrides = await self._overrides(identity.account_id)
        monthly_limit = overrides.monthly_token_limit or policy.monthly_token_limit
        used = await self.supabase.monthly_tokens_used(identity.account_id)
        if used >= monthly_limit:
            raise UsageLimitError("Monthly token limit reached for the current billing period")
        return monthly_limit - used

    def resolve_effective_concurrency(self, policy: PlanPolicy, overrides: LimitOverrides) -> int:
        return overrides.concurrent_generations or policy.concurrent_generations
