-- Nexa: monthly usage rollup RPC for GET /v1/usage.
-- Idempotent; safe to re-run. Apply after 0001_full_nexcoder_nexa.sql.

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
