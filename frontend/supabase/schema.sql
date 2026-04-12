-- Run in Supabase: SQL Editor → New query → Paste → Run

create table if not exists public.patent_drafts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users (id) on delete set null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists patent_drafts_user_id_idx on public.patent_drafts (user_id);

alter table public.patent_drafts enable row level security;

-- Logged-in users: own rows only
create policy "patent_drafts_select_own"
  on public.patent_drafts for select
  using (auth.uid() is not null and auth.uid() = user_id);

create policy "patent_drafts_insert_own"
  on public.patent_drafts for insert
  with check (auth.uid() is not null and auth.uid() = user_id);

create policy "patent_drafts_update_own"
  on public.patent_drafts for update
  using (auth.uid() is not null and auth.uid() = user_id);

-- For anonymous dev saves (no login), run `schema.dev_anon.sql` separately.
