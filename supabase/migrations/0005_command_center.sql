-- Nexa Command Center buildout: DB-backed gateway API keys and the
-- service configuration store (system prompts, routing, agent config).

-- ============================================================================
-- 1. GATEWAY API KEYS — managed via the admin dashboard.
-- Tokens are stored hashed; the plaintext is shown once at creation.
-- ============================================================================
create table if not exists public.ai_gateway_keys (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  key_hash      text not null unique,
  key_prefix    text not null,
  account_id    text not null,
  plan          text not null default 'starter',
  enabled       boolean not null default true,
  created_by    text,
  last_used_at  timestamptz,
  created_at    timestamptz not null default now()
);

create index if not exists ai_gateway_keys_hash_idx on public.ai_gateway_keys (key_hash);

alter table public.ai_gateway_keys enable row level security;
drop policy if exists ai_gateway_keys_service_all on public.ai_gateway_keys;
create policy ai_gateway_keys_service_all on public.ai_gateway_keys
  for all to service_role with check (true);

-- ============================================================================
-- 2. SERVICE CONFIG — versioned key/value store for prompts, routing,
-- agent behavior. NexCoder reads published values via /v1/config/{key}.
-- ============================================================================
create table if not exists public.ai_service_config (
  key         text primary key,
  value       jsonb not null,
  updated_by  text,
  updated_at  timestamptz not null default now()
);

alter table public.ai_service_config enable row level security;
drop policy if exists ai_service_config_service_all on public.ai_service_config;
create policy ai_service_config_service_all on public.ai_service_config
  for all to service_role with check (true);
drop policy if exists ai_service_config_read on public.ai_service_config;
create policy ai_service_config_read on public.ai_service_config
  for select to authenticated using (true);

-- Seed the default configuration entries.
insert into public.ai_service_config (key, value, updated_by) values
  ('system_prompt', '{"content": "You are NexCoder AI, an expert coding assistant. Answer with precision and use code blocks with language identifiers.", "version": 1}', 'seed'),
  ('routing_rules', '{"rules": [{"priority": 1, "condition": "model_unavailable", "action": "fallback", "target": "stepfun-ai/step-3.7-flash"}, {"priority": 2, "condition": "provider_rate_limited", "action": "retry_after", "target": "30"}]}', 'seed'),
  ('agent_config', '{"max_iterations": 12, "planning_enabled": true, "parallel_tools": true, "memory_enabled": true, "context_strategy": "compact", "sub_agents": ["coder", "planner", "reviewer", "debugger"]}', 'seed')
on conflict (key) do nothing;
