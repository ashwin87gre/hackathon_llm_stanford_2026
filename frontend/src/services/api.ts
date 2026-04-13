import type { PatentDraftState, PriorArtHit } from '../types/draft'

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/$/, '')

function useDraftBackend(): boolean {
  return Boolean(API_BASE)
}

/** True when `VITE_API_BASE_URL` points at a running `draft_gen/service.py` server. */
export function isDraftBackendConfigured(): boolean {
  return useDraftBackend()
}

async function postGenerateSection(body: {
  description: string
  section: string
  prior_sections: Record<string, string>
}): Promise<string> {
  const res = await fetch(`${API_BASE}/generate-section`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const err = (await res.json()) as { detail?: unknown }
      if (typeof err.detail === 'string') detail = err.detail
      else if (Array.isArray(err.detail)) detail = JSON.stringify(err.detail)
    } catch {
      detail = (await res.text()) || detail
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  const data = (await res.json()) as { content: string }
  return data.content
}

/** Split technical panel text into backend section keys (see `draft_gen/service.py`). */
function parseTechnicalDescription(s: string): {
  background: string
  detailed_description: string
} {
  const bgMarker = '## BACKGROUND\n'
  const ddMarker = '\n\n## DETAILED DESCRIPTION\n'
  if (s.includes(bgMarker) && s.includes(ddMarker)) {
    const i = s.indexOf(bgMarker) + bgMarker.length
    const j = s.indexOf(ddMarker)
    return {
      background: s.slice(i, j).trim(),
      detailed_description: s.slice(j + ddMarker.length).trim(),
    }
  }
  return { background: '', detailed_description: s.trim() }
}

// --- Step 1 -----------------------------------------------------------------

export async function createInventionDescription(userInput: string): Promise<string> {
  if (useDraftBackend()) {
    const t = userInput.trim()
    if (!t) {
      return 'Describe the problem your invention solves, the main components, and how they interact.'
    }
    return t
  }
  await delay(650)
  if (!userInput.trim()) {
    return 'Describe the problem your invention solves, the main components, and how they interact.'
  }
  return `[Draft — offline preview]\n\nBased on your input, a concise invention description would appear here.\n\n---\n${userInput.trim()}`
}

// --- Step 2 -----------------------------------------------------------------

export async function generateTitle(inventionDescription: string): Promise<string> {
  if (useDraftBackend()) {
    return postGenerateSection({
      description: inventionDescription,
      section: 'title',
      prior_sections: {},
    })
  }
  await delay(450)
  const hint = inventionDescription.split('\n')[0]?.slice(0, 60) || 'the disclosed invention'
  return `[Title — offline] System and method relating to ${hint.trim()}…`
}

export async function generateAbstract(
  inventionDescription: string,
  title: string,
): Promise<string> {
  if (useDraftBackend()) {
    return postGenerateSection({
      description: inventionDescription,
      section: 'summary',
      prior_sections: { title },
    })
  }
  await delay(700)
  const head = title.trim() || 'System and method for improved operation'
  return `[Abstract — offline]\n\n${head}. Technical approaches in this space often lack robust handling of real-world constraints. The disclosed invention provides a structured solution aligned with the following invention summary.\n\n${inventionDescription.slice(0, 400)}${inventionDescription.length > 400 ? '…' : ''}`
}

// --- Step 3 -----------------------------------------------------------------

export async function generateTechnicalDescription(
  draft: Pick<PatentDraftState, 'inventionDescription' | 'title' | 'abstract'>,
): Promise<string> {
  if (useDraftBackend()) {
    const background = await postGenerateSection({
      description: draft.inventionDescription,
      section: 'background',
      prior_sections: { title: draft.title, summary: draft.abstract },
    })
    const detailed_description = await postGenerateSection({
      description: draft.inventionDescription,
      section: 'detailed_description',
      prior_sections: {
        title: draft.title,
        summary: draft.abstract,
        background,
      },
    })
    return `## BACKGROUND\n${background}\n\n## DETAILED DESCRIPTION\n${detailed_description}`
  }
  await delay(750)
  return `[Technical description — offline]\n\n## TECHNICAL FIELD\nRelated to the domain described in the invention summary.\n\n## BACKGROUND\n${draft.abstract.slice(0, 200)}…\n\n## DETAILED DESCRIPTION OF EMBODIMENTS\nEmbodiments may include the elements implied by your invention description, with implementation details supplied by the backend.`
}

// --- Step 4 -----------------------------------------------------------------

export async function generateClaims(
  draft: Pick<PatentDraftState, 'inventionDescription' | 'title' | 'abstract' | 'technicalDescription'>,
): Promise<string> {
  if (useDraftBackend()) {
    const { background, detailed_description } = parseTechnicalDescription(draft.technicalDescription)
    const prior: Record<string, string> = {
      title: draft.title,
      summary: draft.abstract,
    }
    if (background) prior.background = background
    if (detailed_description) prior.detailed_description = detailed_description
    return postGenerateSection({
      description: draft.inventionDescription,
      section: 'claims',
      prior_sections: prior,
    })
  }
  await delay(800)
  const hint = draft.title.slice(0, 48).trim() || 'the disclosed subject matter'
  return `[Claims — offline]\n\n1. A system comprising: a processor; a memory storing instructions that, when executed, cause the system to perform operations comprising — [claim body generated from your draft, informed by: ${hint}].\n\n2. The system of claim 1, wherein …\n\n3. A method comprising …`
}

export async function searchPriorArt(claims: string, inventionDescription: string): Promise<PriorArtHit[]> {
  await delay(600)
  const q = (claims || inventionDescription).slice(0, 80)
  return [
    {
      id: '1',
      title: `[Prior art — offline] Query context: "${q}…"`,
      snippet: 'Representative prior-art snippet would be returned from your patent search pipeline.',
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

export async function requestDrawingsFromDraft(_draft: PatentDraftState): Promise<void> {
  await delay(400)
}

// --- Step 6 -----------------------------------------------------------------

export async function submitPremiumLawyerReview(_draft: PatentDraftState): Promise<void> {
  await delay(500)
}
