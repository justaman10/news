-- Core schema for the personal newspaper.
--
-- Content tables (articles, editions, stories, sports, status) are written only by
-- the backend worker, which connects as the database owner and bypasses RLS.
-- The website reads them with the public "anon" key, so they get read-only
-- policies. User tables (profiles, bookmarks, history, prep progress) are private
-- to each signed-in user.

-- ─── Raw items pulled from sources ───────────────────────────────────────────
create table if not exists public.articles (
  id            bigint generated always as identity primary key,
  url           text not null,
  title         text not null,
  snippet       text not null default '',
  source        text not null,
  feed_url      text not null,
  category      text not null,
  image_url     text,
  published_at  timestamptz,
  fetched_at    timestamptz not null default now(),
  search        tsvector generated always as (
                  to_tsvector('english', title || ' ' || snippet)) stored,
  unique (url, category)
);
create index if not exists articles_category_time
  on public.articles (category, (coalesce(published_at, fetched_at)) desc);
create index if not exists articles_fetched on public.articles (fetched_at desc);
create index if not exists articles_search on public.articles using gin (search);

create table if not exists public.feed_state (
  feed_url       text primary key,
  category       text not null,
  etag           text,
  last_modified  text,
  last_ok        timestamptz,
  last_error     text,
  last_count     int not null default 0,
  updated_at     timestamptz not null default now()
);

-- ─── Daily editions ──────────────────────────────────────────────────────────
create table if not exists public.editions (
  id            bigint generated always as identity primary key,
  edition_date  date not null unique,
  number        int not null,
  status        text not null default 'draft' check (status in ('draft', 'published')),
  ai            boolean not null default false,
  lead_note     text not null default '',
  quiz          jsonb not null default '[]',
  front_page    bigint[] not null default '{}',   -- story ids, lead story first
  stats         jsonb not null default '{}',
  published_at  timestamptz,
  created_at    timestamptz not null default now()
);

create table if not exists public.stories (
  id             bigint generated always as identity primary key,
  edition_id     bigint not null references public.editions on delete cascade,
  category       text not null,
  rank           int not null,
  depth          text not null check (depth in ('headlines', 'brief', 'deep')),
  headline       text not null,
  summary        text not null default '',
  why_it_matters text not null default '',
  background     text not null default '',
  perspectives   jsonb not null default '[]',   -- [{label, view}]
  implications   text not null default '',
  key_terms      jsonb not null default '[]',   -- [{term, definition}]
  interview      jsonb not null default '[]',   -- [{question, answer}]
  talking_point  text not null default '',
  deep_dive      jsonb,                          -- null until written
  importance     int not null default 5,
  image_url      text,
  image_source   text,
  primary_url    text not null,
  sources        jsonb not null default '[]',   -- [{title, url, source, published_at}]
  published_at   timestamptz,
  created_at     timestamptz not null default now(),
  search         tsvector generated always as (
                   to_tsvector('english', headline || ' ' || summary || ' ' || why_it_matters)) stored
);
create index if not exists stories_edition on public.stories (edition_id, category, rank);
create index if not exists stories_search on public.stories using gin (search);

create table if not exists public.sections (
  edition_id  bigint not null references public.editions on delete cascade,
  category    text not null,
  intro       text not null default '',
  concept     jsonb,                              -- {name, explanation, example, question, answer}
  primary key (edition_id, category)
);

-- Later reporting on a story, attached by the half-hourly refresh.
create table if not exists public.story_updates (
  story_id    bigint not null references public.stories on delete cascade,
  article_id  bigint not null references public.articles on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (story_id, article_id)
);

-- ─── Sports ──────────────────────────────────────────────────────────────────
create table if not exists public.sports_events (
  id                text primary key,             -- provider:external id
  sport             text not null,
  competition       text not null,
  starts_at         timestamptz not null,
  status            text not null check (status in ('scheduled', 'live', 'finished', 'postponed', 'cancelled')),
  home              text not null,
  away              text not null default '',
  home_score        text,
  away_score        text,
  detail            text not null default '',
  url               text,
  updated_at        timestamptz not null default now()
);
create index if not exists sports_time on public.sports_events (starts_at);

-- ─── Job monitoring ──────────────────────────────────────────────────────────
create table if not exists public.job_runs (
  id           bigint generated always as identity primary key,
  job          text not null,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  status       text not null default 'running' check (status in ('running', 'ok', 'partial', 'failed')),
  summary      jsonb not null default '{}',
  error        text
);
create index if not exists job_runs_job_time on public.job_runs (job, started_at desc);

create or replace view public.site_status with (security_invoker = true) as
  select job,
         max(finished_at) filter (where status in ('ok', 'partial')) as last_success,
         max(started_at) as last_attempt
  from public.job_runs
  group by job;

-- ─── Per-user data ───────────────────────────────────────────────────────────
create table if not exists public.profiles (
  user_id     uuid primary key references auth.users on delete cascade,
  prefs       jsonb not null default '{}',
  updated_at  timestamptz not null default now()
);

create table if not exists public.bookmarks (
  user_id     uuid not null references auth.users on delete cascade,
  story_id    bigint not null references public.stories on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (user_id, story_id)
);

create table if not exists public.reading_history (
  user_id   uuid not null references auth.users on delete cascade,
  story_id  bigint not null references public.stories on delete cascade,
  read_at   timestamptz not null default now(),
  primary key (user_id, story_id)
);

create table if not exists public.prep_known (
  user_id     uuid not null references auth.users on delete cascade,
  item_key    text not null,
  created_at  timestamptz not null default now(),
  primary key (user_id, item_key)
);

-- ─── Row level security ──────────────────────────────────────────────────────
alter table public.articles        enable row level security;
alter table public.feed_state      enable row level security;
alter table public.editions        enable row level security;
alter table public.stories         enable row level security;
alter table public.sections        enable row level security;
alter table public.story_updates   enable row level security;
alter table public.sports_events   enable row level security;
alter table public.job_runs        enable row level security;
alter table public.profiles        enable row level security;
alter table public.bookmarks       enable row level security;
alter table public.reading_history enable row level security;
alter table public.prep_known      enable row level security;

drop policy if exists "public read" on public.articles;
create policy "public read" on public.articles for select to anon, authenticated using (true);
drop policy if exists "public read" on public.feed_state;
create policy "public read" on public.feed_state for select to anon, authenticated using (true);
drop policy if exists "public read" on public.sports_events;
create policy "public read" on public.sports_events for select to anon, authenticated using (true);
drop policy if exists "public read" on public.job_runs;
create policy "public read" on public.job_runs for select to anon, authenticated using (true);

drop policy if exists "published only" on public.editions;
create policy "published only" on public.editions for select to anon, authenticated
  using (status = 'published');
drop policy if exists "published only" on public.stories;
create policy "published only" on public.stories for select to anon, authenticated
  using (exists (select 1 from public.editions e where e.id = edition_id and e.status = 'published'));
drop policy if exists "published only" on public.sections;
create policy "published only" on public.sections for select to anon, authenticated
  using (exists (select 1 from public.editions e where e.id = edition_id and e.status = 'published'));
drop policy if exists "public read" on public.story_updates;
create policy "public read" on public.story_updates for select to anon, authenticated using (true);

drop policy if exists "own rows" on public.profiles;
create policy "own rows" on public.profiles for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "own rows" on public.bookmarks;
create policy "own rows" on public.bookmarks for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "own rows" on public.reading_history;
create policy "own rows" on public.reading_history for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "own rows" on public.prep_known;
create policy "own rows" on public.prep_known for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

grant usage on schema public to anon, authenticated;
grant select on public.articles, public.feed_state, public.editions, public.stories,
  public.sections, public.story_updates, public.sports_events, public.job_runs,
  public.site_status to anon, authenticated;
grant select, insert, update, delete on public.profiles, public.bookmarks,
  public.reading_history, public.prep_known to authenticated;
