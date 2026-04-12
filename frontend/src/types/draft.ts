export type PriorArtHit = {
  id: string
  title: string
  snippet: string
  /** Populated when backend returns a link (e.g. patent URL). */
  sourceUrl?: string
}

export type DraftImage = {
  id: string
  caption: string
  /** Local preview only until Supabase Storage or API upload exists. */
  previewUrl: string
  fileName: string
}

/** Mirrors `draft_gen.generate_draft.format_draft` sections + wizard-only fields. */
export type PatentDraftState = {
  userInput: string
  inventionDescription: string
  title: string
  abstract: string
  technicalDescription: string
  claims: string
  priorArt: PriorArtHit[]
  images: DraftImage[]
  premiumLawyerReview: boolean
}

export function emptyDraft(): PatentDraftState {
  return {
    userInput: '',
    inventionDescription: '',
    title: '',
    abstract: '',
    technicalDescription: '',
    claims: '',
    priorArt: [],
    images: [],
    premiumLawyerReview: false,
  }
}
