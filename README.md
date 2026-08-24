# Nexa — AI Gateway Service

Nexa sits between Nexcoder clients and external AI providers (NVIDIA hosted
NIM first). Clients authenticate with their existing Supabase identity or a
Nexa gateway key; provider credentials live **only** in Nexa's server
environment.

```
NEXCODER ── HTTPS (Bearer) ──► NEXA ──► NVIDIA NIM API ──► model
                              │
                 Auth · Policies · Routing · Usage
```

## Endpoints

| Method | Path                  | Auth | Purpose |
|--------|-----------------------|------|---------|
| GET    | `/v1/health`          | none | Liveness + provider configuration status |
| GET    | `/v1/models`          | Bearer | Plan-filtered logical model catalog |
| POST   | `/v1/chat/completions`| Bearer | OpenAI-compatible chat, streaming + non-streaming |
| POST   | `/v1/agent/run`       | Bearer | Agent workload foundation (V1: no server-side tool execution) |

Every response carries an `X-Request-Id` header (`nexa_req_...`).

## Authentication

Send `Authorization: Bearer <credential>`:

1. **Supabase access token** — verified against the project's auth server;
   the caller's plan is read from `profiles.plan` with the service-role key.
   This is what desktop/web/mobile clients get from the normal login flow.
2. **Gateway key** (`nxkey_...`) — static token mapped to `(account_id,
   plan)` via `NEXA_GATEWAY_KEYS`, for machine/service builds.

Client-supplied user/account IDs are never trusted as authentication; a body
claiming a different `account_id` is rejected (`AUTHORIZATION_FAILED`).

## Models

Clients use the real NVIDIA NIM model ids end-to-end (see `GET /v1/models`):

- `stepfun-ai/step-3.7-flash` — Step 3.7 Flash (fast, vision)
- `nvidia/nemotron-3-ultra-550b-a55b` — Nemotron 3 Ultra (flagship reasoning)
- `nvidia/nemotron-3-super-120b-a12b` — Nemotron 3 Super (balanced)
- `deepseek-ai/deepseek-v4-flash-0731` — DeepSeek V4 Flash (efficient coding)

Ids pass through to the provider unchanged. To swap a mapping without a
client update, set `NEXA_MODEL_ROUTES=<id>=<new-provider-model>,...`.

## Policies

Plan policies are centralized in `nexa/policies/plans.py` and mirror the
Polar-driven plans in `profiles.plan`: `starter`, `plus`, `pro`, `premium`,
`business-standard`, `business-plus`, `enterprise`. Each defines RPM/RPH,
concurrent generations, monthly tokens, allowed models and max context.
Per-account overrides come from `ai_account_limits`.

Errors are normalized to stable codes: `INVALID_REQUEST`,
`AUTHENTICATION_FAILED`, `AUTHORIZATION_FAILED`, `RATE_LIMITED`,
`CONCURRENCY_LIMIT`, `USAGE_LIMIT`, `PROVIDER_UNAVAILABLE`,
`PROVIDER_RATE_LIMIT`, `MODEL_UNAVAILABLE`, `REQUEST_TIMEOUT`,
`CLIENT_CANCELLED`, `INTERNAL_ERROR`. Raw upstream errors never reach
clients.

## Configuration

Copy `.env.example` and fill in values. Secrets are read server-side only;
never prefix them with frontend-exposed conventions.

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | yes (token auth) | Same project as Nexcoder |
| `SUPABASE_SERVICE_ROLE_KEY` | for plan lookup + usage writes | Server-side only |
| `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, `NVIDIA_DEFAULT_MODEL` | yes | Provider credentials |
| `NEXA_MODEL_ROUTES` | recommended | logical=provider pairs |
| `NEXA_GATEWAY_KEYS` | optional | `token:account_id:plan` triples |
| `NEXA_ALLOWED_ORIGINS` | recommended | Trusted origins; wildcard only in dev |
| `REDIS_URL` | optional | Shared rate-limit/concurrency state (multi-instance) |

Rate limiting and concurrency use an in-process store by default. Run a
single instance or provide Redis-backed state before scaling out.

## Database

Apply `supabase/migrations/0001_ai_tables.sql` in the Nexcoder Supabase
project (idempotent). It creates:

- `ai_requests` — per-request metadata (tokens, latency, status; no content)
- `ai_usage` — daily rollups
- `ai_model_catalog` — dynamic catalog overrides
- `ai_account_limits` — per-account policy overrides
- `ai_monthly_tokens(account_id)` — RPC used for monthly usage checks

All tables are RLS-locked against client access; only the service role writes.

## Run

```bash
python -m venv .venv && .venv\Scripts\pip install -e ".[dev]"
uvicorn nexa.main:app --port 8000        # development
pytest                                   # test suite
```

### Docker / any host

```bash
docker build -t nexa .
docker run --rm -p 8000:8000 --env-file .env nexa
```

The app is plain ASGI (FastAPI): deploy unchanged to Cloud Run, Fly.io,
Azure App Service, AWS App Runner, Kubernetes, or any VPS. On Vercel, host
it behind Fluid Compute / a dedicated service for long-lived streams — the
chat path is request/stream based and holds no state between requests, so
migrating to background workers for future agent runs requires no rewrite.

## Observability

Structured logs include `request_id`, `user_id`, `account_id`, `model`,
`provider`, `status`, `latency_ms`. Prompts/responses and credentials are
never logged.

## Client integration (Nexcoder)

```
NEXA_API_URL=https://api.trynexa-ai.com/v1
NEXA_MODEL=stepfun-ai/step-3.7-flash
NEXA_API_KEY=<gateway credential>
```

The client `.env` must not contain provider keys. For local development:
`NEXA_API_URL=http://127.0.0.1:8000/v1`. local develeopment 
