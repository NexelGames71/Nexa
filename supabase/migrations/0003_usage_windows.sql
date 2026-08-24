-- Nexa usage windows: 5-hour allowance + 7-day weekly cycle with one
-- complimentary renewal. All quota transitions are atomic (row locks) so
-- concurrent requests, multiple devices and retries cannot double-spend
-- or double-renew. Idempotent per request_id. Apply after 0001/0002.

-- ============================================================================
-- 1. STATE + RESERVATIONS
-- ============================================================================
create table if not exists public.ai_usage_state (
  account_id                   text primary key,
  usage_started_at             timestamptz,
  five_hour_limit              bigint not null default 0,
  five_hour_used               bigint not null default 0,
  five_hour_window_started_at  timestamptz,
  five_hour_window_ends_at     timestamptz,
  daily_limit                  bigint not null default 0,
  daily_used                   bigint not null default 0,
  daily_window_started_at      timestamptz,
  daily_window_ends_at         timestamptz,
  weekly_limit                 bigint not null default 0,
  weekly_used                  bigint not null default 0,
  weekly_cycle_started_at      timestamptz,
  weekly_cycle_ends_at         timestamptz,
  weekly_renewal_count         integer not null default 1,
  weekly_renewals_used         integer not null default 0,
  updated_at                   timestamptz not null default now(),
  created_at                   timestamptz not null default now()
);

create table if not exists public.ai_usage_reservations (
  request_id   text primary key,
  account_id   text not null,
  units        bigint not null,
  state        text not null default 'reserved',  -- reserved|consumed|released
  created_at   timestamptz not null default now()
);

create index if not exists ai_usage_reservations_account_idx
  on public.ai_usage_reservations (account_id, created_at);

alter table public.ai_usage_state enable row level security;
alter table public.ai_usage_reservations enable row level security;
create policy ai_usage_state_service_all on public.ai_usage_state
  for all to service_role with check (true);
create policy ai_usage_reservations_service_all on public.ai_usage_reservations
  for all to service_role with check (true);

-- ============================================================================
-- 2. AUTHORIZE + RESERVE (atomic)
-- ============================================================================
create or replace function public.ai_authorize_usage(
  p_account_id text,
  p_five_hour_limit bigint,
  p_daily_limit bigint,
  p_weekly_limit bigint,
  p_weekly_renewal_count integer,
  p_units bigint,
  p_request_id text
)
returns json language plpgsql as $$
declare
  v_state public.ai_usage_state;
  v_now timestamptz := now();
  v_renewal_granted boolean := false;
begin
  -- Idempotency: a retried request_id never charges twice.
  if exists (select 1 from public.ai_usage_reservations r
             where r.request_id = p_request_id and r.state = 'reserved') then
    return json_build_object('allowed', true, 'duplicate', true);
  end if;

  insert into public.ai_usage_state (account_id)
  values (p_account_id)
  on conflict (account_id) do nothing;

  select * into v_state from public.ai_usage_state
  where account_id = p_account_id
  for update;

  -- First successful request starts both clocks (never before).
  if v_state.usage_started_at is null then
    v_state.usage_started_at := v_now;
    v_state.five_hour_window_started_at := v_now;
    v_state.five_hour_window_ends_at := v_now + interval '5 hours';
    v_state.weekly_cycle_started_at := v_now;
    v_state.weekly_cycle_ends_at := v_now + interval '7 days';
  end if;

  -- Lazy five-hour reset.
  if v_state.five_hour_window_ends_at is not null
     and v_now >= v_state.five_hour_window_ends_at then
    v_state.five_hour_used := 0;
    v_state.five_hour_window_started_at := v_now;
    v_state.five_hour_window_ends_at := v_now + interval '5 hours';
  end if;

  -- Lazy daily reset.
  if v_state.daily_window_ends_at is not null
     and v_now >= v_state.daily_window_ends_at then
    v_state.daily_used := 0;
    v_state.daily_window_started_at := v_now;
    v_state.daily_window_ends_at := v_now + interval '24 hours';
  end if;

  -- Lazy weekly reset: restores usage AND renewal eligibility.
  if v_state.weekly_cycle_ends_at is not null
     and v_now >= v_state.weekly_cycle_ends_at then
    v_state.weekly_used := 0;
    v_state.weekly_renewals_used := 0;
    v_state.weekly_cycle_started_at := v_now;
    v_state.weekly_cycle_ends_at := v_now + interval '7 days';
  end if;

  -- Keep configured limits current.
  v_state.five_hour_limit := p_five_hour_limit;
  v_state.daily_limit := p_daily_limit;
  v_state.weekly_limit := p_weekly_limit;
  v_state.weekly_renewal_count := p_weekly_renewal_count;

  if v_state.five_hour_used + p_units > v_state.five_hour_limit then
    return json_build_object(
      'allowed', false,
      'window', 'five_hour',
      'reset_at', v_state.five_hour_window_ends_at);
  end if;

  if v_state.daily_used + p_units > v_state.daily_limit then
    return json_build_object(
      'allowed', false,
      'window', 'daily',
      'reset_at', v_state.daily_window_ends_at);
  end if;

  if v_state.weekly_used + p_units > v_state.weekly_limit then
    if v_state.weekly_renewals_used < v_state.weekly_renewal_count then
      -- Complimentary renewal: exactly one per weekly cycle. The row lock
      -- guarantees concurrent exhaustion cannot grant it twice.
      v_state.weekly_renewals_used := v_state.weekly_renewals_used + 1;
      v_state.weekly_used := 0;
      v_renewal_granted := true;
    else
      return json_build_object(
        'allowed', false,
        'window', 'weekly',
        'reset_at', v_state.weekly_cycle_ends_at,
        'renewal_available', false);
    end if;
  end if;

  v_state.five_hour_used := v_state.five_hour_used + p_units;
  v_state.daily_used := v_state.daily_used + p_units;
  v_state.weekly_used := v_state.weekly_used + p_units;

  update public.ai_usage_state set
    usage_started_at = v_state.usage_started_at,
    five_hour_limit = v_state.five_hour_limit,
    five_hour_used = v_state.five_hour_used,
    five_hour_window_started_at = v_state.five_hour_window_started_at,
    five_hour_window_ends_at = v_state.five_hour_window_ends_at,
    daily_limit = v_state.daily_limit,
    daily_used = v_state.daily_used,
    daily_window_started_at = v_state.daily_window_started_at,
    daily_window_ends_at = v_state.daily_window_ends_at,
    weekly_limit = v_state.weekly_limit,
    weekly_used = v_state.weekly_used,
    weekly_cycle_started_at = v_state.weekly_cycle_started_at,
    weekly_cycle_ends_at = v_state.weekly_cycle_ends_at,
    weekly_renewal_count = v_state.weekly_renewal_count,
    weekly_renewals_used = v_state.weekly_renewals_used,
    updated_at = v_now
  where account_id = p_account_id;

  insert into public.ai_usage_reservations (request_id, account_id, units)
  values (p_request_id, p_account_id, p_units)
  on conflict (request_id) do nothing;

  return json_build_object(
    'allowed', true,
    'renewal_granted', v_renewal_granted,
    'five_hour_used', v_state.five_hour_used,
    'weekly_used', v_state.weekly_used);
end;
$$;

grant execute on function public.ai_authorize_usage(text, bigint, bigint, integer, bigint, text) to service_role;

-- ============================================================================
-- 3. FINALIZE (reconcile actual token usage) + RELEASE (infra failure)
-- ============================================================================
create or replace function public.ai_finalize_usage(
  p_request_id text,
  p_actual_units bigint
)
returns void language plpgsql as $$
declare
  v_reservation public.ai_usage_reservations;
  v_delta bigint;
begin
  select * into v_reservation from public.ai_usage_reservations
  where request_id = p_request_id and state = 'reserved'
  for update;
  if v_reservation is null then
    return;  -- already finalized/released, or unknown: nothing to do
  end if;

  v_delta := greatest(0, p_actual_units) - v_reservation.units;

  update public.ai_usage_state set
    five_hour_used = greatest(0, five_hour_used + v_delta),
    weekly_used = greatest(0, weekly_used + v_delta),
    updated_at = now()
  where account_id = v_reservation.account_id;

  update public.ai_usage_reservations
  set state = 'consumed' where request_id = p_request_id;
end;
$$;

grant execute on function public.ai_finalize_usage(text, bigint) to service_role;

create or replace function public.ai_release_usage(p_request_id text)
returns void language plpgsql as $$
declare
  v_reservation public.ai_usage_reservations;
begin
  select * into v_reservation from public.ai_usage_reservations
  where request_id = p_request_id and state = 'reserved'
  for update;
  if v_reservation is null then
    return;
  end if;

  update public.ai_usage_state set
    five_hour_used = greatest(0, five_hour_used - v_reservation.units),
    weekly_used = greatest(0, weekly_used - v_reservation.units),
    updated_at = now()
  where account_id = v_reservation.account_id;

  update public.ai_usage_reservations
  set state = 'released' where request_id = p_request_id;
end;
$$;

grant execute on function public.ai_release_usage(text) to service_role;

-- ============================================================================
-- 4. STATE SNAPSHOT for GET /v1/usage (lazily initializes the row)
-- ============================================================================
create or replace function public.ai_get_usage_state(
  p_account_id text,
  p_five_hour_limit bigint,
  p_daily_limit bigint,
  p_weekly_limit bigint,
  p_weekly_renewal_count integer
)
returns json language plpgsql as $$
declare
  v_state public.ai_usage_state;
begin
  insert into public.ai_usage_state (account_id)
  values (p_account_id)
  on conflict (account_id) do nothing;

  select * into v_state from public.ai_usage_state
  where account_id = p_account_id
  for update;

  update public.ai_usage_state set
    five_hour_limit = p_five_hour_limit,
    weekly_limit = p_weekly_limit,
    weekly_renewal_count = p_weekly_renewal_count,
    updated_at = now()
  where account_id = p_account_id;

  return json_build_object(
    'usage_started_at', v_state.usage_started_at,
    'five_hour_used', v_state.five_hour_used,
    'five_hour_window_started_at', v_state.five_hour_window_started_at,
    'five_hour_window_ends_at', v_state.five_hour_window_ends_at,
    'daily_used', v_state.daily_used,
    'daily_window_started_at', v_state.daily_window_started_at,
    'daily_window_ends_at', v_state.daily_window_ends_at,
    'weekly_used', v_state.weekly_used,
    'weekly_cycle_started_at', v_state.weekly_cycle_started_at,
    'weekly_cycle_ends_at', v_state.weekly_cycle_ends_at,
    'weekly_renewals_used', v_state.weekly_renewals_used
  );
end;
$$;

grant execute on function public.ai_get_usage_state(text, bigint, bigint, integer) to service_role;
