-- Nexa Command Center: admin audit trail.

create table if not exists public.ai_admin_audit (
  id          bigint generated always as identity primary key,
  action      text not null,            -- model.updated, key.created, ...
  resource    text,                     -- affected resource id
  admin       text not null default 'admin',
  details     jsonb not null default '{}',
  created_at  timestamptz not null default now()
);

create index if not exists ai_admin_audit_created_idx on public.ai_admin_audit (created_at desc);

alter table public.ai_admin_audit enable row level security;
drop policy if exists ai_admin_audit_service_all on public.ai_admin_audit;
create policy ai_admin_audit_service_all on public.ai_admin_audit
  for all to service_role with check (true);
