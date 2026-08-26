-- Nexa Command Center: richer daily analytics.

create or replace function public.ai_daily_stats(p_days integer)
returns table (day date, requests bigint, total_tokens bigint,
               success bigint, failed bigint, input_tokens bigint, output_tokens bigint)
language sql stable security definer set search_path = public as $$
  select date_trunc('day', started_at)::date as day,
         count(*)::bigint as requests,
         coalesce(sum(total_tokens), 0)::bigint as total_tokens,
         count(*) filter (where status = 'success')::bigint as success,
         count(*) filter (where status <> 'success')::bigint as failed,
         coalesce(sum(input_tokens), 0)::bigint as input_tokens,
         coalesce(sum(output_tokens), 0)::bigint as output_tokens
  from public.ai_requests
  where started_at >= now() - make_interval(days => greatest(1, least(90, p_days)))
  group by 1 order by 1;
$$;
