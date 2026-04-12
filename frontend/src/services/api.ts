import type { PatentDraftState, PriorArtHit } from '../types/draft'

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * Replace with `import.meta.env.VITE_API_BASE_URL` + `fetch` when FastAPI (or similar) exists.
 * Python reference: `draft_gen/generate_draft.py` — `generate_patent_draft(description)`.
 */
// const API = import.meta.env.VITE_API_BASE_URL ?? ''

// --- Step 1 -----------------------------------------------------------------

/** TODO: POST /api/v1/draft/invention-description — normalize/expand user notes into a formal invention description. */
export async function createInventionDescription(userInput: string): Promise<string> {
  await delay(650)
  if (!userInput.trim()) {
    return 'Describe the problem your invention solves, the main components, and how they interact.'
  }
  return `[Draft — connect Python]\n\nBased on your input, a concise invention description would appear here.\n\n---\n${userInput.trim()}`
}

/** TODO: POST /api/v1/draft/title — body: { inventionDescription }. Maps to `title` in `generate_patent_draft` output. */
export async function generateTitle(inventionDescription: string): Promise<string> {
  await delay(450)
  const hint = inventionDescription.split('\n')[0]?.slice(0, 60) || 'the disclosed invention'
  return `[Title — connect Python] System and method relating to ${hint.trim()}…`
}

// --- Step 2 -----------------------------------------------------------------

/** TODO: POST /api/v1/draft/abstract — body: { inventionDescription, title? }. Backend may use GENERATE_ABSTRACT from `draft_gen/prompts.py`. */
export async function generateAbstract(
  inventionDescription: string,
  title: string,
): Promise<string> {
  await delay(700)
  const head = title.trim() || 'System and method for improved operation'
  return `[Abstract — connect Python]\n\n${head}. Technical approaches in this space often lack robust handling of real-world constraints. The disclosed invention provides a structured solution aligned with the following invention summary.\n\n${inventionDescription.slice(0, 400)}${inventionDescription.length > 400 ? '…' : ''}`
}

// --- Step 3 -----------------------------------------------------------------

/** TODO: POST /api/v1/draft/technical-description — body: prior sections; maps to detailed description in `generate_patent_draft`. */
export async function generateTechnicalDescription(draft: Pick<PatentDraftState, 'inventionDescription' | 'title' | 'abstract'>): Promise<string> {
  await delay(750)
  return `[Technical description — connect Python]\n\n## TECHNICAL FIELD\nRelated to the domain described in the invention summary.\n\n## BACKGROUND\n${draft.abstract.slice(0, 200)}…\n\n## DETAILED DESCRIPTION OF EMBODIMENTS\nEmbodiments may include the elements implied by your invention description, with implementation details supplied by the backend.`
}

// --- Step 4 -----------------------------------------------------------------

/** TODO: POST /api/v1/draft/claims — body: full context dict. */
export async function generateClaims(draft: Pick<PatentDraftState, 'inventionDescription' | 'title' | 'abstract' | 'technicalDescription'>): Promise<string> {
  await delay(800)
  const hint = draft.title.slice(0, 48).trim() || 'the disclosed subject matter'
  return `[Claims — connect Python]\n\n1. A system comprising: a processor; a memory storing instructions that, when executed, cause the system to perform operations comprising — [claim body generated from your draft, informed by: ${hint}].\n\n2. The system of claim 1, wherein …\n\n3. A method comprising …`
}

/**
 * TODO: POST /api/v1/prior-art/search — JSON `{ "query": string, "limit": number }`.
 * Python: `search_prior_art/service.py` → wrap `prior_art.search_prior_art` / `generate_queries`.
 */
export async function searchPriorArt(claims: string, inventionDescription: string): Promise<PriorArtHit[]> {
  await delay(600)
  const q = (claims || inventionDescription).slice(0, 80)
  return [
    {
      id: '1',
      title: `[Prior art — connect Python] Query context: "${q}…"`,
      snippet: 'Representative prior-art snippet would be returned from your patent search pipeline (e.g. Cohere + retrieval).',
      sourceUrl: undefined,
    },
    {
      id: '2',
      title: 'Secondary reference (placeholder)',
      snippet: 'Another hit with title, abstract fragment, and optional link to USPTO or internal corpus.',
    },
  ]
}

// --- Step 5 -----------------------------------------------------------------

/** TODO: POST /api/v1/drawings — send invention JSON / text; Python `drawing_generator`. */
export async function requestDrawingsFromDraft(_draft: PatentDraftState): Promise<void> {
  await delay(400)
  // Backend would return image URLs or job id; UI uses local uploads until then.
}

// --- Step 6 -----------------------------------------------------------------

/** TODO: POST /api/v1/review/lawyer-request — persist to Supabase + notify. */
export async function submitPremiumLawyerReview(_draft: PatentDraftState): Promise<void> {
  await delay(500)
}
