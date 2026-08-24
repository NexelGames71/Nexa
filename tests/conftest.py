"""Shared fixtures: fake Supabase, fake NVIDIA provider, test app + client."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from nexa.appstate import NexaState
from nexa.auth import Authenticator
from nexa.config import Settings
from nexa.main import create_app
from nexa.policies.concurrency import ConcurrencyManager
from nexa.policies.service import PolicyService
from nexa.providers.base import AIProvider, ChatRequest, ChatResponse, ModelInfo, Usage
from nexa.services.supabase import SupabaseService
from nexa.services.usage import UsageTracker


class FakeSupabase(SupabaseService):
    """Never touches the network."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings or Settings())
        self.users: dict[str, dict[str, Any]] = {}
        self.plans: dict[str, str] = {}
        self.inserted: list[tuple[str, dict]] = []

    def add_user(self, token: str, user_id: str = "u-1", plan: str = "pro") -> None:
        self.users[token] = {"user_id": user_id, "email": f"{user_id}@test", "account_id": user_id}
        self.plans[user_id] = plan

    async def verify_access_token(self, token: str) -> dict[str, Any] | None:
        return self.users.get(token)

    async def get_user_plan(self, user_id: str) -> str | None:
        return self.plans.get(user_id)

    async def insert_usage(self, table: str, record: dict) -> bool:
        self.inserted.append((table, record))
        return True

    async def get_account_limit_overrides(self, account_id: str) -> dict | None:
        return None

    async def monthly_tokens_used(self, account_id: str) -> int:
        return 0

    async def get_model_catalog_rows(self) -> list[dict]:
        return []


class FakeNVIDIAProvider(AIProvider):
    """Scriptable in-memory NVIDIA stand-in; SSE format matches the real one."""

    name = "nvidia"
    configured = True

    def __init__(self) -> None:
        self.calls: list[ChatRequest] = []
        self.fail_with: Exception | None = None
        self.stream_chunks: list[dict] = [
            {"choices": [{"delta": {"role": "assistant", "content": "Hello"}}]},
            {"choices": [{"delta": {"content": ", world"}}]},
            {"choices": [{"finish_reason": "stop"}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ]

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if self.fail_with:
            raise self.fail_with
        self.calls.append(request)
        return ChatResponse(
            content="ok", model=request.model,
            usage=Usage(input_tokens=3, output_tokens=2),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[dict]:
        self.calls.append(request)
        if self.fail_with:
            raise self.fail_with
        for chunk in self.stream_chunks:
            yield chunk

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="meta/llama-3.1-70b-instruct")]

    async def health(self) -> bool:
        return True


def make_settings() -> Settings:
    return Settings(
        nvidia_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_default_model="stepfun-ai/step-3.7-flash",
        model_routes={
            # Identity mapping: ids pass through unchanged.
            "stepfun-ai/step-3.7-flash": "stepfun-ai/step-3.7-flash",
            "nvidia/nemotron-3-ultra-550b-a55b": "nvidia/nemotron-3-ultra-550b-a55b",
            "nvidia/nemotron-3-super-120b-a12b": "nvidia/nemotron-3-super-120b-a12b",
            "deepseek-ai/deepseek-v4-flash-0731": "deepseek-ai/deepseek-v4-flash-0731",
        },
        allowed_origins=["http://localhost:3000"],
        default_plan="starter",
    )


@pytest.fixture()
def supabase() -> FakeSupabase:
    return FakeSupabase()


@pytest.fixture()
def nvidia() -> FakeNVIDIAProvider:
    return FakeNVIDIAProvider()


@pytest.fixture()
def state(supabase: FakeSupabase, nvidia: FakeNVIDIAProvider) -> NexaState:
    settings = make_settings()
    authenticator = Authenticator(supabase, {}, settings.default_plan)
    policies = PolicyService(settings, supabase)
    usage = UsageTracker(supabase)
    from nexa.policies.usage_windows import UsageService

    return NexaState(
        settings=settings,
        authenticator=authenticator,
        policies=policies,
        usage=usage,
        supabase=supabase,
        concurrency=ConcurrencyManager(),
        providers={nvidia.name: nvidia},
        usage_windows=UsageService(supabase),
    )


@pytest_asyncio.fixture()
async def client(state: NexaState) -> AsyncIterator[AsyncClient]:
    app = create_app(state.settings)
    app.state.nexa = state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


VALID_CHAT_BODY = {
    "model": "stepfun-ai/step-3.7-flash",
    "messages": [{"role": "user", "content": "hi"}],
}


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
