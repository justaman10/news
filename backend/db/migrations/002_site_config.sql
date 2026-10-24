-- Settings the website needs (categories, default preferences), published by the
-- worker from config/sources.yaml so there is a single source of truth.
create table if not exists public.site_config (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);
alter table public.site_config enable row level security;
drop policy if exists "public read" on public.site_config;
create policy "public read" on public.site_config for select to anon, authenticated using (true);
grant select on public.site_config to anon, authenticated;
