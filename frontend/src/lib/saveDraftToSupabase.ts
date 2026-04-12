import { getSupabase } from './supabaseClient'
import type { PatentDraftState } from '../types/draft'

export type SaveDraftResult =
  | { ok: true; id: string }
  | { ok: false; error: string }

/**
 * Inserts a row into `patent_drafts` (see `supabase/schema.sql`).
 * Requires a matching RLS policy for your auth setup (or dev policy).
 */
export async function saveDraftToSupabase(
  draft: PatentDraftState,
): Promise<SaveDraftResult> {
  const supabase = getSupabase()
  if (!supabase) {
    return { ok: false, error: 'Supabase URL/key missing in .env' }
  }

  const {
    data: { session },
  } = await supabase.auth.getSession()

  const payload = {
    user_input: draft.userInput,
    invention_description: draft.inventionDescription,
    title: draft.title,
    abstract: draft.abstract,
    technical_description: draft.technicalDescription,
    claims: draft.claims,
    prior_art: draft.priorArt,
    images: draft.images.map(({ previewUrl, ...rest }) => ({
      ...rest,
      /** previewUrl is often a blob: URL — omit or replace after Storage upload */
      previewUrl: previewUrl.startsWith('blob:') ? null : previewUrl,
    })),
    premium_lawyer_review: draft.premiumLawyerReview,
  }

  const row: { payload: typeof payload; user_id?: string | null } = { payload }
  if (session?.user?.id) {
    row.user_id = session.user.id
  }

  const { data, error } = await supabase
    .from('patent_drafts')
    .insert(row)
    .select('id')
    .single()

  if (error) {
    return { ok: false, error: error.message }
  }
  if (!data?.id) {
    return { ok: false, error: 'No id returned' }
  }
  return { ok: true, id: data.id as string }
}
