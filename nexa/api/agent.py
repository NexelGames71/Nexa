"""POST /v1/agent/run — foundation for Nexcoder agent workloads.

V1 contract: validate + authorize the run request, reserve a generation
slot, and execute a routed model turn with agent context. Remote tool
execution is deliberately deferred: tool requests are returned to the
client as `pending_tools` for client-side, permission-checked execution.
Nexa never executes arbitrary tools merely because a model asks.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from nexa.api.deps import current_identity, get_nexa_state
from nexa.appstate import NexaState
from nexa.auth import AuthIdentity, apply_identity, ensure_account_match
from nexa.context import RequestContext, log_request
from nexa.errors import INTERNAL_ERROR, INVALID_REQUEST, NexaError
from nexa.providers.base import ChatRequest
from nexa.providers.registry import resolve_route
from nexa.routing.catalog import known_model

router = APIRouter()

MAX_TOOLS = 64
MAX_CONTEXT_KEYS = 128


def _validate_agent_body(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise NexaError(INVALID_REQUEST, "Request body must be a JSON object")

    task = data.get("task")
    if not isinstance(task, str) or not task.strip():
        raise NexaError(INVALID_REQUEST, "'task' must be a non-empty string")

    model = data.get("model", "nvidia/nemotron-3-ultra-550b-a55b")
    if not isinstance(model, str) or not known_model(model):
        raise NexaError(INVALID_REQUEST, "Invalid model identifier")

    context = data.get("context", {})
    if not isinstance(context, dict) or len(context) > MAX_CONTEXT_KEYS:
        raise NexaError(INVALID_REQUEST, "'context' must be an object with at most "
                                         f"{MAX_CONTEXT_KEYS} entries")

    tools = data.get("tools", [])
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise NexaError(INVALID_REQUEST, f"'tools' must be an array of at most {MAX_TOOLS}")
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise NexaError(INVALID_REQUEST, f"tools[{i}] must be an object with a 'name'")

    workspace = data.get("workspace", {})
    if not isinstance(workspace, dict):
        raise NexaError(INVALID_REQUEST, "'workspace' must be an object")

    return {
        "task": task,
        "model": model,
        "context": context,
        "tools": tools,
        "workspace": workspace,
        "account_id": data.get("account_id"),
    }


@router.post("/agent/run")
async def agent_run(
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

    body = _validate_agent_body(raw)
    ensure_account_match(identity, body["account_id"])
    ctx.model = body["model"]
    ctx.provider = "nvidia"

    policy = await state.policies.enforce_rate_limits(
        identity, http_request.client.host if http_request.client else None
    )
    state.policies.check_model_allowed(identity, body["model"])

    provider_name, provider_model = resolve_route(state.settings, body["model"])
    provider = state.providers[provider_name]

    # Tool declarations are recorded but never executed server-side in V1.
    declared_tools = [t["name"] for t in body["tools"]]

    system_prompt = (
        "You are NexCoder Agent. Work on the user's task step by step. "
        "If you need a tool, emit one <tool_call> request at a time; the host "
        "environment decides whether it is permitted."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Task: {body['task']}\n\n"
                f"Workspace metadata: {list(body['workspace'].keys())}\n"
                f"Available tools (names only): {declared_tools}\n"
                f"Context keys: {sorted(body['context'].keys())}"
            ),
        },
    ]

    state.concurrency.acquire_generation_slot(identity.account_id, policy.concurrent_generations)
    estimated_units = max(1, (len(body["task"]) + len(body["task"]) // 3) // 3)
    decision = await state.usage_windows.authorize(
        identity.account_id, policy, estimated_units, ctx.request_id)
    if not decision.allowed:
        state.concurrency.release_generation_slot(identity.account_id)
        from nexa.errors import FIVE_HOUR_LIMIT_REACHED, WEEKLY_LIMIT_REACHED
        from datetime import datetime, timezone
        code = (FIVE_HOUR_LIMIT_REACHED if decision.window == "five_hour"
                else WEEKLY_LIMIT_REACHED)
        message = ("Your 5-hour usage limit has been reached."
                   if decision.window == "five_hour"
                   else "Your weekly usage limit has been reached.")
        reset_iso = datetime.fromtimestamp(
            decision.reset_at or time.time(), tz=timezone.utc).isoformat()
        error = NexaError(code, message, details={
            "reset_at": reset_iso,
            "retry_after_seconds": decision.retry_after_seconds})
        error.headers = {"Retry-After": str(max(1, decision.retry_after_seconds))}
        raise error
    try:
        response = await provider.chat(
            ChatRequest(model=provider_model, messages=messages, temperature=0.2,
                        max_tokens=min(4096, policy.maximum_context // 2))
        )
    finally:
        state.concurrency.release_generation_slot(identity.account_id)

    usage = response.usage
    await state.usage_windows.finalize(
        identity.account_id, ctx.request_id,
        usage.total_tokens if usage else estimated_units)
    await state.usage.record(ctx, usage=usage, status="success")
    log_request(ctx, "success")

    return JSONResponse(
        {
            "request_id": ctx.request_id,
            "status": "completed",
            "run": {
                "task": body["task"],
                "model": body["model"],
                "provider_turns": 1,
                "output": response.content,
            },
            "pending_tools": [],  # V1 never executes tools server-side
            "declared_tools": declared_tools,
            "usage": {
                "prompt_tokens": usage.input_tokens if usage else 0,
                "completion_tokens": usage.output_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            },
        }
    )


@router.post("/agent/run/stream")
async def agent_run_stream(http_request: Request):
    """Reserved: streaming agent turns will reuse the chat streaming path."""
    raise NexaError("NOT_IMPLEMENTED", "Streaming agent runs arrive in a later milestone",
                    http_status=501)

