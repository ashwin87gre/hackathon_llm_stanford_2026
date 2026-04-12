-- Optional: run AFTER schema.sql if you want to test saves without Supabase Auth.
-- Remove these policies before production.

create policy "patent_drafts_dev_anon_insert"
  on public.patent_drafts for insert
  with check (user_id is null);

create policy "patent_drafts_dev_anon_select"
  on public.patent_drafts for select
  using (user_id is null);
