-- Nexa admin-managed model catalog v2.
-- Adds capacity/plan fields to ai_model_catalog and seeds the current
-- lineup. Admins manage rows via /v1/admin/catalog; the gateway serves
-- the catalog dynamically and clients pick up changes automatically.

alter table public.ai_model_catalog
  add column if not exists context_window bigint,
  add column if not exists max_output_tokens bigint,
  add column if not exists requires_plan text,
  add column if not exists max_tokens integer not null default 8192;

insert into public.ai_model_catalog (
  logical_id, display_name, capabilities, provider, provider_model,
  context_window, max_output_tokens, requires_plan, enabled, sort_order
) values
  ('stepfun-ai/step-3.7-flash',          'Step 3.7 Flash',   '{chat,code,streaming,vision}', 'nvidia',     'stepfun-ai/step-3.7-flash',          65536,  8192, 'starter', true, 1),
  ('nvidia/nemotron-3-ultra-550b-a55b',  'Nemotron 3 Ultra', '{chat,code,streaming,tools,reasoning}', 'nvidia', 'nvidia/nemotron-3-ultra-550b-a55b', 65536, 8192, 'plus', true, 2),
  ('nvidia/nemotron-3-super-120b-a12b',  'Nemotron 3 Super', '{chat,code,streaming,tools}',  'nvidia',     'nvidia/nemotron-3-super-120b-a12b',  65536,  8192, 'plus', true, 3),
  ('deepseek-ai/deepseek-v4-flash-0731', 'DeepSeek V4 Flash','{chat,code,streaming}',        'nvidia',     'deepseek-ai/deepseek-v4-flash-0731', 65536,  8192, 'starter', true, 4),
  ('stealth/ox-alpha',                   'Ox Alpha',         '{chat,code,streaming,reasoning}', 'openrouter', 'stealth/ox-alpha',               65536, 16384, 'starter', true, 5)
on conflict (logical_id) do update set
  display_name = excluded.display_name,
  capabilities = excluded.capabilities,
  provider = excluded.provider,
  provider_model = excluded.provider_model,
  context_window = excluded.context_window,
  max_output_tokens = excluded.max_output_tokens,
  requires_plan = excluded.requires_plan,
  sort_order = excluded.sort_order;

-- RLS already locked down from 0001 (service-write, authenticated-read).
