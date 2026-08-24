-- ============================================================================
-- NEXCODER + NEXA — FULL MIGRATION (ONE FILE)
-- Apply in Supabase dashboard: SQL Editor -> paste -> Run.
-- Idempotent: safe to re-run; creates anything missing, never drops data.
--
-- Sections:
--   1. Plans catalog (Polar tiers)
--   2. Profiles (+ auto-create trigger on signup)
--   3. Organizations + members
--   4. Subscriptions (Polar billing columns)
--   5. Usage events (legacy metering) + Polar webhook log
--   6. AI gateway tables: ai_requests, ai_usage, ai_model_catalog,
--      ai_account_limits (+ monthly-token RPC used by Nexa)
--   7. Row Level Security for everything above
-- ============================================================================

-- ============================================================================
-- 1. PLANS (catalog) -- drives pricing + entitlements
-- ============================================================================
create table if not exists public.plans (
  id               text primary key,          -- 'starter','plus','pro','premium','business-standard','business-plus','enterprise'
  name             text not null,
  best_for         text,
  price_cents      integer,                    -- null = custom (Enterprise); per seat when per_seat = true
  currency         text not null default 'usd',
  billing_interval text not null default 'month',   -- 'month' | 'year' | 'custom'
  per_seat         boolean not null default false,
  plan_type        text not null default 'individual', -- 'individual' | 'team' | 'enterprise'
  sort_order       integer not null default 0,
  is_active        boolean not null default true
);

insert into public.plans (id, name, best_for, price_cents, billing_interval, per_seat, plan_type, sort_order) values
  ('starter',           'Starter',           'Trying NexCoder and using local models', 0,    'month', false, 'individual', 1),
  ('plus',              'Plus',              'Regular individual developers',          2000, 'month', false, 'individual', 2),
  ('pro',               'Pro',               'Daily agent users',                      3900, 'month', false, 'individual', 3),
  ('premium',           'Premium',           'Maximum individual usage',               9900, 'month', false, 'individual', 4),
  ('business-standard', 'Business Standard', 'Development teams',                      4000, 'month', true,  'team',       5),
  ('business-plus',     'Business Plus',     'Advanced teams',                         12000,'month', true,  'team',       6),
  ('enterprise',        'Enterprise',        'Large organizations',                    null, 'custom', true,'enterprise', 7)
on conflict (id) do update set
  name = excluded.name, best_for = excluded.best_for, price_cents = excluded.price_cents,
  billing_interval = excluded.billing_interval, per_seat = excluded.per_seat,
  plan_type = excluded.plan_type, sort_order = excluded.sort_order, is_active = true;

-- ============================================================================
-- 2. PROFILES -- one row per auth user (auto-created via trigger)
-- ============================================================================
create table if not exists public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  email        text,
  full_name    text,
  plan         text not null default 'starter',
  usage_count  integer not null default 0,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table public.profiles alter column plan set default 'starter';
update public.profiles set plan = 'starter' where plan is null or plan = 'free';

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'profiles_plan_fkey') then
    alter table public.profiles
      add constraint profiles_plan_fkey foreign key (plan) references public.plans (id);
  end if;
end $$;

-- Auto-create a profile (default Starter) when a user signs up.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, full_name)
  values (
    new.id, new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Backfill profiles for any pre-existing users.
insert into public.profiles (id, email)
select id, email from auth.users
on conflict (id) do nothing;

-- ============================================================================
-- 3. ORGANIZATIONS + MEMBERS (per-seat team plans)
-- ============================================================================
create table if not exists public.organizations (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  slug       text unique,
  owner_id   uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);

create table if not exists public.organization_members (
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id         uuid not null references auth.users (id) on delete cascade,
  role            text not null default 'member',   -- 'owner' | 'admin' | 'member'
  created_at      timestamptz not null default now(),
  primary key (organization_id, user_id)
);

-- Membership check as SECURITY DEFINER to avoid RLS recursion in policies.
create or replace function public.is_org_member(org uuid)
returns boolean language sql security definer set search_path = public stable as $$
  select exists (
    select 1 from public.organization_members m
    where m.organization_id = org and m.user_id = auth.uid()
  );
$$;

-- ============================================================================
-- 4. SUBSCRIPTIONS (Polar billing state)
-- ============================================================================
create table if not exists public.subscriptions (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid references auth.users (id) on delete cascade,
  organization_id        uuid references public.organizations (id) on delete cascade,
  plan_id                text not null references public.plans (id),
  status                 text not null default 'active', -- active|trialing|past_due|canceled|incomplete
  seats                  integer not null default 1,
  current_period_start   timestamptz,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  stripe_customer_id     text,
  stripe_subscription_id text unique,
  polar_customer_id      text,
  polar_subscription_id  text,
  polar_checkout_id      text,
  polar_product_id       text,
  polar_order_id         text,
  billing_interval       text,
  metadata               jsonb not null default '{}',
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  constraint subscription_subject check (
    (user_id is not null and organization_id is null) or
    (user_id is null and organization_id is not null)
  )
);

create index if not exists subscriptions_user_idx on public.subscriptions (user_id);
create index if not exists subscriptions_org_idx  on public.subscriptions (organization_id);
create unique index if not exists subscriptions_polar_subscription_id_idx
  on public.subscriptions (polar_subscription_id)
  where polar_subscription_id is not null;

-- ============================================================================
-- 5. LEGACY USAGE EVENTS + POLAR WEBHOOK LOG
-- ============================================================================
create table if not exists public.usage_events (
  id              bigint generated always as identity primary key,
  user_id         uuid references auth.users (id) on delete set null,
  organization_id uuid references public.organizations (id) on delete set null,
  event_type      text not null,               -- 'agent_run' | 'input_tokens' | ...
  quantity        integer not null default 1,
  metadata        jsonb not null default '{}',
  created_at      timestamptz not null default now()
);
create index if not exists usage_events_user_idx on public.usage_events (user_id, created_at);
create index if not exists usage_events_org_idx  on public.usage_events (organization_id, created_at);

create table if not exists public.polar_webhook_events (
  id           text primary key,
  event_type   text not null,
  payload      jsonb not null,
  received_at  timestamptz not null default now(),
  processed_at timestamptz
);

-- ============================================================================
-- 6. NEXA AI GATEWAY TABLES
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 6a. ai_requests -- one row per gateway request (metadata only; NEVER stores
--     prompt/response content).
-- ----------------------------------------------------------------------------
create table if not exists public.ai_requests (
  id             uuid primary key default gen_random_uuid(),
  request_id     text unique not null,                 -- nexa_req_...
  user_id        uuid references auth.users (id) on delete set null,
  account_id     text,
  provider       text not null default 'nvidia',
  model          text,                                  -- model id from the catalog
  started_at     timestamptz not null default now(),
  completed_at   timestamptz,
  input_tokens   integer not null default 0,
  output_tokens  integer not null default 0,
  total_tokens   integer not null default 0,
  latency_ms     integer not null default 0,
  status         text not null default 'success',      -- success|error|cancelled
  error_code     text,
  created_at     timestamptz not null default now()
);

create index if not exists ai_requests_user_idx    on public.ai_requests (user_id, created_at);
create index if not exists ai_requests_account_idx on public.ai_requests (account_id, created_at);
create index if not exists ai_requests_model_idx   on public.ai_requests (model, created_at);
create index if not exists ai_requests_status_idx  on public.ai_requests (status);

-- Monthly token usage per account; called by Nexa for usage-limit checks.
create or replace function public.ai_monthly_tokens(p_account_id text)
returns bigint language sql stable security definer set search_path = public as $$
  select coalesce(sum(total_tokens), 0)::bigint
  from public.ai_requests
  where account_id = p_account_id
    and status = 'success'
    and date_trunc('month', started_at) = date_trunc('month', now());
$$;

grant execute on function public.ai_monthly_tokens(text) to service_role;

-- Full monthly usage rollup (requests + token split) for GET /v1/usage.
create or replace function public.ai_monthly_usage(p_account_id text)
returns json language sql stable security definer set search_path = public as $$
  select json_build_object(
    'requests',      count(*)::int,
    'input_tokens',  coalesce(sum(input_tokens), 0)::bigint,
    'output_tokens', coalesce(sum(output_tokens), 0)::bigint,
    'total_tokens',  coalesce(sum(total_tokens), 0)::bigint
  )
  from public.ai_requests
  where account_id = p_account_id
    and status = 'success'
    and date_trunc('month', started_at) = date_trunc('month', now());
$$;

grant execute on function public.ai_monthly_usage(text) to service_role;

-- ----------------------------------------------------------------------------
-- 6b. ai_usage -- optional daily rollups per account/model.
-- ----------------------------------------------------------------------------
create table if not exists public.ai_usage (
  id            bigserial primary key,
  account_id    text not null,
  day           date not null,
  model         text,
  requests      integer not null default 0,
  input_tokens  bigint not null default 0,
  output_tokens bigint not null default 0,
  unique (account_id, day, model)
);

create index if not exists ai_usage_account_day_idx on public.ai_usage (account_id, day desc);

-- ----------------------------------------------------------------------------
-- 6c. ai_model_catalog -- dynamic overrides for GET /v1/models routing.
-- ----------------------------------------------------------------------------
create table if not exists public.ai_model_catalog (
  logical_id     text primary key,        -- e.g. stepfun-ai/step-3.7-flash | ...
  display_name   text,
  capabilities   text[] not null default '{}',
  provider       text not null default 'nvidia',
  provider_model text not null,           -- concrete NVIDIA NIM model id
  enabled        boolean not null default true,
  sort_order     integer not null default 0,
  updated_at     timestamptz not null default now()
);

insert into public.ai_model_catalog (logical_id, display_name, capabilities, provider_model, sort_order) values
  ('stepfun-ai/step-3.7-flash',              'Step 3.7 Flash',   '{chat,code,streaming,vision}', 'stepfun-ai/step-3.7-flash',              1),
  ('nvidia/nemotron-3-ultra-550b-a55b',      'Nemotron 3 Ultra', '{chat,code,streaming,tools}',  'nvidia/nemotron-3-ultra-550b-a55b',      2),
  ('nvidia/nemotron-3-super-120b-a12b',      'Nemotron 3 Super', '{chat,code,streaming,tools}',  'nvidia/nemotron-3-super-120b-a12b',      3),
  ('deepseek-ai/deepseek-v4-flash-0731',     'DeepSeek V4 Flash','{chat,code,streaming}',        'deepseek-ai/deepseek-v4-flash-0731',     4)
on conflict (logical_id) do update set
  display_name = excluded.display_name,
  capabilities = excluded.capabilities,
  provider_model = excluded.provider_model,
  sort_order = excluded.sort_order;

-- ----------------------------------------------------------------------------
-- 6d. ai_account_limits -- per-account policy overrides read by Nexa.
-- ----------------------------------------------------------------------------
create table if not exists public.ai_account_limits (
  account_id             text primary key,
  plan_override          text references public.plans (id),
  requests_per_minute    integer,
  requests_per_hour      integer,
  concurrent_generations integer,
  monthly_token_limit    bigint,
  updated_at             timestamptz not null default now()
);

-- Keep updated_at fresh everywhere it exists.
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();
drop trigger if exists subscriptions_set_updated_at on public.subscriptions;
create trigger subscriptions_set_updated_at before update on public.subscriptions
  for each row execute function public.set_updated_at();

-- ============================================================================
-- 7. ROW LEVEL SECURITY
-- ============================================================================
alter table public.plans                  enable row level security;
alter table public.profiles               enable row level security;
alter table public.organizations          enable row level security;
alter table public.organization_members   enable row level security;
alter table public.subscriptions          enable row level security;
alter table public.usage_events           enable row level security;
alter table public.polar_webhook_events   enable row level security;
alter table public.ai_requests            enable row level security;
alter table public.ai_usage               enable row level security;
alter table public.ai_model_catalog       enable row level security;
alter table public.ai_account_limits      enable row level security;

-- Plans: readable by everyone (drives the public pricing page).
drop policy if exists plans_read_all on public.plans;
create policy plans_read_all on public.plans for select to anon, authenticated using (true);

-- Profiles: a user reads/updates only their own.
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles for select using (auth.uid() = id);
drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles for update
  using (auth.uid() = id) with check (auth.uid() = id);

-- Organizations: members read; owner manages.
drop policy if exists orgs_select_member on public.organizations;
create policy orgs_select_member on public.organizations for select
  using (owner_id = auth.uid() or public.is_org_member(id));
drop policy if exists orgs_insert_owner on public.organizations;
create policy orgs_insert_owner on public.organizations for insert
  with check (owner_id = auth.uid());
drop policy if exists orgs_update_owner on public.organizations;
create policy orgs_update_owner on public.organizations for update
  using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Organization members: visible to members of the same org.
drop policy if exists org_members_select on public.organization_members;
create policy org_members_select on public.organization_members for select
  using (public.is_org_member(organization_id));

-- Subscriptions: the owning user, or members of the owning org, may read.
drop policy if exists subscriptions_select on public.subscriptions;
create policy subscriptions_select on public.subscriptions for select
  using (
    user_id = auth.uid()
    or (organization_id is not null and public.is_org_member(organization_id))
  );

-- Usage events: owning user / org members may read (writes are service-side).
drop policy if exists usage_select on public.usage_events;
create policy usage_select on public.usage_events for select
  using (
    user_id = auth.uid()
    or (organization_id is not null and public.is_org_member(organization_id))
  );

-- Polar webhook log: no client access at all.
drop policy if exists polar_webhook_events_no_client_access on public.polar_webhook_events;
create policy polar_webhook_events_no_client_access
  on public.polar_webhook_events for select using (false);

-- AI tables: clients can never read or write directly. Nexa writes with the
-- service-role key, which bypasses RLS. The catalog is readable by logged-in
-- users (it drives the UI), everything else is service-only.
drop policy if exists ai_requests_no_client_access on public.ai_requests;
create policy ai_requests_no_client_access on public.ai_requests for select using (false);
drop policy if exists ai_requests_service_write on public.ai_requests;
create policy ai_requests_service_write on public.ai_requests
  for insert to service_role with check (true);

drop policy if exists ai_usage_no_client_access on public.ai_usage;
create policy ai_usage_no_client_access on public.ai_usage for select using (false);
drop policy if exists ai_usage_service_all on public.ai_usage;
create policy ai_usage_service_all on public.ai_usage
  for all to service_role with check (true);

drop policy if exists ai_model_catalog_read on public.ai_model_catalog;
create policy ai_model_catalog_read on public.ai_model_catalog
  for select to authenticated using (enabled = true);
drop policy if exists ai_model_catalog_service_all on public.ai_model_catalog;
create policy ai_model_catalog_service_all on public.ai_model_catalog
  for all to service_role with check (true);

drop policy if exists ai_account_limits_no_client_access on public.ai_account_limits;
create policy ai_account_limits_no_client_access on public.ai_account_limits
  for select using (false);
drop policy if exists ai_account_limits_service_all on public.ai_account_limits;
create policy ai_account_limits_service_all on public.ai_account_limits
  for all to service_role with check (true);
