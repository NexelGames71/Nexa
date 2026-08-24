"""Application state container shared across routes via request.app.state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nexa.auth import Authenticator
from nexa.config import Settings
from nexa.policies.concurrency import ConcurrencyManager
from nexa.policies.service import PolicyService
from nexa.providers.base import AIProvider
from nexa.services.supabase import SupabaseService
from nexa.services.usage import UsageTracker


@dataclass
class NexaState:
    settings: Settings
    authenticator: Authenticator
    policies: PolicyService
    usage: UsageTracker
    supabase: SupabaseService
    concurrency: ConcurrencyManager
    providers: dict[str, AIProvider]
    version: str = "0.1.0"

    def registry_items(self):
        return self.providers.items()
