-- Nexa Command Center: webhooks, config backups, daily analytics.

-- ============================================================================
-- 1. WEBHOOKS — outgoing event notifications.
-- ============================================================================
create table if not exists public.ai_webhooks (
  id          uuid primary key default gen_random_uuid(),
  url         text not null,
  secret      text,
  events      text[] not null default '{}',
  enabled     boolean not null default true,
  created_at  timestamptz not null default now()
);

alter table public.ai_webhooks enable row level security;
drop policy if exists ai_webhooks_service_all on public.ai_webhooks;
create policy ai_webhooks_service_all on public.ai_webhooks
  for all to service_role with check (true);

-- ============================================================================
-- 2. CONFIG BACKUPS — full configuration snapshots.
-- ============================================================================
create table if not exists public.ai_config_backups (
  id          uuid primary key default gen_random_uuid(),
  label       text not null default 'snapshot',
  payload     jsonb not null,
  created_by  text,
  created_at  timestamptz not null default now()
);

alter table public.ai_config_backups enable row level security;
drop policy if exists ai_config_backups_service_all on public.ai_config_backups;
create policy ai_config_backups_service_all on public.ai_config_backups
  for all to service_role with check (true);

-- ============================================================================
-- 3. DAILY ANALYTICS — requests/tokens per day for dashboard charts.
-- ============================================================================
create or replace function public.ai_daily_stats(p_days integer)
returns table (day date, requests bigint, total_tokens bigint)
language sql stable security definer set search_path = public as $$
  select date_trunc('day', started_at)::date as day,
         count(*)::bigint as requests,
         coalesce(sum(total_tokens), 0)::bigint as total_tokens
  from public.ai_requests
  where started_at >= now() - make_interval(days => greatest(1, least(90, p_days)))
  group by 1 order by 1;
$$;

grant execute on function public.ai_daily_stats(integer) to service_role;
