"""POST /v1/chat/completions — OpenAI-compatible chat with streaming support.

Pipeline: authenticate → validate → rate limit → model permission →
concurrency slot → route to provider → (stream | buffer) → record usage.
Slots are always released via try/finally.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from nexa.api.deps import client_ip, current_identity, get_nexa_state
from nexa.appstate import NexaState
from nexa.auth import AuthIdentity, apply_identity, ensure_account_match
from nexa.context import RequestContext, log_request
from nexa.errors import (
    CLIENT_CANCELLED,
    FIVE_HOUR_LIMIT_REACHED,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    PROVIDER_UNAVAILABLE,
    WEEKLY_LIMIT_REACHED,
    NexaError,
)
from nexa.policies.plans import PlanPolicy
from nexa.policies.plans import PlanPolicy as _PlanPolicy  # noqa: F401
from nexa.providers.base import ChatRequest, Usage
from nexa.providers.registry import resolve_route
from nexa.routing.catalog import known_model

router = APIRouter()

MAX_MESSAGES = 256


class ChatCompletionBody:
    __slots__ = ("model", "messages", "temperature", "max_tokens", "stream",
                 "account_id", "extras")

    def __init__(self, data: dict[str, Any]) -> None:
        self.model = data.get("model")
        self.messages = data.get("messages")
        self.temperature = data.get("temperature")
        self.max_tokens = data.get("max_tokens")
        self.stream = bool(data.get("stream", False))
        self.account_id = data.get("account_id")
        self.extras: dict[str, Any] = {}

    def collect_extras(self, data: dict[str, Any]) -> None:
        """Forward OpenAI-compatible optional fields to the provider.

        `tools`/`tool_choice` are essential: native function-calling breaks
        silently without them. The rest are standard sampling controls and
        the reasoning extensions some NIM models accept.
        """
        passthrough = (
            "tools", "tool_choice", "top_p", "stop", "response_format",
            "presence_penalty", "frequency_penalty", "seed", "logprobs",
            "top_logprobs", "reasoning_effort", "reasoning_budget",
            "chat_template_kwargs",
        )
        for key in passthrough:
            if key in data and data[key] is not None:
                self.extras[key] = data[key]


def parse_body(data: Any) -> ChatCompletionBody:
    if not isinstance(data, dict):
        raise NexaError(INVALID_REQUEST, "Request body must be a JSON object")
    body = ChatCompletionBody(data)

    if not body.model or not isinstance(body.model, str):
        raise NexaError(INVALID_REQUEST, "Missing or invalid 'model'")
    if not known_model(body.model):
        raise NexaError(INVALID_REQUEST, "Invalid model identifier")

    if not isinstance(body.messages, list) or not body.messages:
        raise NexaError(INVALID_REQUEST, "'messages' must be a non-empty array")
    if len(body.messages) > MAX_MESSAGES:
        raise NexaError(INVALID_REQUEST, f"'messages' exceeds maximum of {MAX_MESSAGES}")
    for i, message in enumerate(body.messages):
        if not isinstance(message, dict):
            raise NexaError(INVALID_REQUEST, f"messages[{i}] must be an object")
        role = message.get("role")
        if role not in ("system", "user", "assistant", "tool"):
            raise NexaError(INVALID_REQUEST, f"messages[{i}].role is invalid")
        content = message.get("content")
        # content may be a string or a structured parts array (vision etc.)
        if content is None or (
            not isinstance(content, str) and not isinstance(content, list)
        ):
            raise NexaError(INVALID_REQUEST, f"messages[{i}].content is required")

    if body.temperature is not None:
        if not isinstance(body.temperature, (int, float)) or not (0 <= body.temperature <= 2):
            raise NexaError(INVALID_REQUEST, "'temperature' must be between 0 and 2")
    if body.max_tokens is not None:
        if not isinstance(body.max_tokens, int) or not (1 <= body.max_tokens <= 32768):
            raise NexaError(INVALID_REQUEST, "'max_tokens' must be an integer between 1 and 32768")

    body.collect_extras(data)
    if "tools" in body.extras:
        tools = body.extras["tools"]
        if not isinstance(tools, list) or not all(isinstance(t, dict) for t in tools):
            raise NexaError(INVALID_REQUEST, "'tools' must be an array of tool objects")
        if len(tools) > 128:
            raise NexaError(INVALID_REQUEST, "'tools' exceeds maximum of 128")
    if "tool_choice" in body.extras:
        choice = body.extras["tool_choice"]
        if not isinstance(choice, (str, dict)):
            raise NexaError(INVALID_REQUEST, "'tool_choice' must be a string or object")
    if "top_p" in body.extras:
        top_p = body.extras["top_p"]
        if not isinstance(top_p, (int, float)) or not (0 < top_p <= 1):
            raise NexaError(INVALID_REQUEST, "'top_p' must be between 0 and 1")

    return body


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_sse(error: NexaError) -> str:
    return _sse(error.to_payload())


async def _estimate_usage(messages: list[dict], content: str) -> Usage:
    def est(text: str) -> int:
        return max(1, len(text) // 3) if text else 0

    input_tokens = sum(
        est(m.get("content")) if isinstance(m.get("content"), str) else 0
        for m in messages
    )
    return Usage(input_tokens=input_tokens, output_tokens=est(content))


@router.post("/chat/completions")
async def chat_completions(
    http_request: Request,
    state: NexaState = Depends(get_nexa_state),
    identity: AuthIdentity = Depends(current_identity),
):
    ctx: RequestContext = http_request.state.nexa_ctx
    apply_identity(ctx, identity)

    try:
        raw = await http_request.json()
    except Exception:
        raise NexaError(INVALID_REQUEST, "Body must be valid JSON")

    body = parse_body(raw)
    ensure_account_match(identity, body.account_id)
    ctx.model = body.model
    ctx.provider = "nvidia"

    policy = await state.policies.enforce_rate_limits(identity, client_ip(http_request))
    state.policies.check_model_allowed(identity, body.model)
    state.policies.validate_context_size(identity, body.messages)

    provider_name, provider_model = resolve_route(state.settings, body.model)
    provider = state.providers[provider_name]

    # Usage windows: reserve estimated input tokens before the provider call.
    # Idempotent per request_id; finalized with real token usage afterwards.
    estimated_units = max(1, sum(
        len(str(m.get("content", ""))) for m in body.messages
    ) // 3)
    decision = await state.usage_windows.authorize(
        identity.account_id, policy, estimated_units, ctx.request_id)
    if not decision.allowed:
        code = (FIVE_HOUR_LIMIT_REACHED if decision.window == "five_hour"
                else WEEKLY_LIMIT_REACHED)
        message = ("Your 5-hour usage limit has been reached."
                   if decision.window == "five_hour"
                   else "Your weekly usage limit has been reached.")
        from datetime import datetime, timezone
        reset_iso = datetime.fromtimestamp(
            decision.reset_at or time.time(), tz=timezone.utc).isoformat()
        error = NexaError(
            code, message,
            details={"reset_at": reset_iso,
                     "retry_after_seconds": decision.retry_after_seconds,
                     "renewal_available": code == WEEKLY_LIMIT_REACHED and False},
        )
        error.headers = {"Retry-After": str(max(1, decision.retry_after_seconds))}
        await state.usage.record(ctx, status="error", error_code=code)
        raise error

    chat_request = ChatRequest(
        model=provider_model,
        messages=body.messages,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        stream=body.stream,
        stream_options={"include_usage": True} if body.stream else None,
        extras=body.extras,
    )

    concurrency_cap = policy.concurrent_generations
    state.concurrency.acquire_generation_slot(identity.account_id, concurrency_cap)
    try:
        if body.stream:
            return StreamingResponse(
                _stream_response(state, ctx, provider, chat_request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
                background=_ReleaseSlotBackground(state, identity.account_id),
            )
        response = await provider.chat(chat_request)
        usage = response.usage or await _estimate_usage(body.messages, response.content or "")
        await state.usage_windows.finalize(
            identity.account_id, ctx.request_id, usage.total_tokens)
        await state.usage.record(ctx, usage=usage, status="success")
        message: dict[str, Any] = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            message["tool_calls"] = response.tool_calls
        return JSONResponse(
            {
                "id": ctx.request_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": response.finish_reason or "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": usage.input_tokens,
                    "completion_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                },
            }
        )
    except NexaError as exc:
        await state.usage_windows.release(identity.account_id, ctx.request_id)
        await state.usage.record(ctx, status="error", error_code=exc.code)
        raise
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("nexa.api.chat").exception(
            "chat completion failed request_id=%s", ctx.request_id
        )
        await state.usage_windows.release(identity.account_id, ctx.request_id)
        internal = type(exc).__name__
        await state.usage.record(ctx, status="error", error_code=INTERNAL_ERROR)
        raise NexaError(INTERNAL_ERROR, "Internal error", internal=internal) from exc
    finally:
        if not body.stream:
            state.concurrency.release_generation_slot(identity.account_id)


class _ReleaseSlotBackground:
    """Runs after the streaming response finishes; always releases the slot."""

    def __init__(self, state: NexaState, account_id: str) -> None:
        self.state = state
        self.account_id = account_id

    async def __call__(self) -> None:
        self.state.concurrency.release_generation_slot(self.account_id)


async def _stream_response(
    state: NexaState,
    ctx: RequestContext,
    provider: Any,
    chat_request: ChatRequest,
):
    """Forward upstream SSE chunks to the client as they arrive."""
    content_parts: list[str] = []
    final_usage: Usage | None = None
    upstream_finish: str | None = None
    started = True

    try:
        async for chunk in provider.stream(chat_request):
            choices = chunk.get("choices") or [{}]
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str):
                content_parts.append(piece)

            usage_raw = chunk.get("usage")
            if isinstance(usage_raw, dict):
                final_usage = Usage(
                    input_tokens=int(usage_raw.get("prompt_tokens", 0)),
                    output_tokens=int(usage_raw.get("completion_tokens", 0)),
                )
            if choices[0].get("finish_reason"):
                upstream_finish = choices[0].get("finish_reason")

            if started:
                yield _sse({"id": ctx.request_id, "object": "chat.completion.chunk", "model": ctx.model})
                started = False

            # Forward the delta VERBATIM — tool_calls fragments, reasoning
            # fields and content all belong to the client. Rebuilding the
            # delta here strips native tool-calling and breaks agents.
            payload = {
                "id": ctx.request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": ctx.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": choices[0].get("finish_reason"),
                    }
                ],
            }
            yield _sse(payload)

        if final_usage is None:
            final_usage = await _estimate_usage([], "".join(content_parts))

        yield _sse(
            {
                "id": ctx.request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": ctx.model,
                # Preserve the upstream finish reason ("stop", "tool_calls",
                # "length") — clients branch on it for tool-call handling.
                "choices": [{"index": 0, "delta": {},
                             "finish_reason": upstream_finish or "stop"}],
                "usage": {
                    "prompt_tokens": final_usage.input_tokens,
                    "completion_tokens": final_usage.output_tokens,
                    "total_tokens": final_usage.total_tokens,
                },
            }
        )
        yield "data: [DONE]\n\n"

        await state.usage_windows.finalize(
            ctx.account_id or "", ctx.request_id,
            final_usage.total_tokens)
        await state.usage.record(ctx, usage=final_usage, status="success")
        log_request(ctx, "success")
    except NexaError as exc:
        try:
            yield _error_sse(exc)
            yield "data: [DONE]\n\n"
        except Exception:  # client already gone
            pass
        await state.usage_windows.release(ctx.account_id or "", ctx.request_id)
        await state.usage.record(ctx, status="error", error_code=exc.code)
        log_request(ctx, "error", error=exc)
    except Exception:
        # Upstream disconnect or unexpected failure mid-stream.
        normalized = NexaError(PROVIDER_UNAVAILABLE, "AI provider stream failed",
                               internal="stream_interrupted")
        try:
            yield _error_sse(normalized)
            yield "data: [DONE]\n\n"
        except Exception:  # client cancelled / disconnected
            await state.usage_windows.release(ctx.account_id or "", ctx.request_id)
            await state.usage.record(ctx, status="cancelled",
                                     error_code=CLIENT_CANCELLED)
            return
        await state.usage_windows.release(ctx.account_id or "", ctx.request_id)
        await state.usage.record(ctx, status="error", error_code=normalized.code)
        log_request(ctx, "error", error=normalized)

