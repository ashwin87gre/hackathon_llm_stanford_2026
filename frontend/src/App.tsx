import { useCallback, useEffect, useRef, useState } from 'react'
import { Stepper } from './components/Stepper'
import {
  createInventionDescription,
  generateAbstract,
  generateClaims,
  generateTechnicalDescription,
  generateTitle,
  requestDrawingsFromDraft,
  searchPriorArt,
  submitPremiumLawyerReview,
} from './services/api'
import { isSupabaseConfigured } from './lib/supabaseClient'
import { saveDraftToSupabase } from './lib/saveDraftToSupabase'
import { emptyDraft, type DraftImage, type PatentDraftState } from './types/draft'

const STEP_LABELS = [
  'Invention',
  'Abstract',
  'Technical',
  'Claims',
  'Drawings',
  'Review',
] as const

const panelClass =
  'rounded-2xl border border-white/10 bg-surface-elevated/80 p-6 shadow-[0_0_0_1px_rgba(255,255,255,0.03)_inset] backdrop-blur-xl sm:p-8'

const labelClass = 'mb-2 block text-sm font-medium text-slate-400'
const inputClass =
  'w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-accent/50 focus:ring-2 focus:ring-accent/20'
const textareaClass = `${inputClass} min-h-[200px] resize-y font-normal leading-relaxed`

function App() {
  const [step, setStep] = useState(1)
  const [draft, setDraft] = useState<PatentDraftState>(emptyDraft)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [supabaseMsg, setSupabaseMsg] = useState<string | null>(null)
  const [supabaseSaving, setSupabaseSaving] = useState(false)
  const genLock = useRef(0)
  const draftRef = useRef(draft)
  draftRef.current = draft

  const seededStep2 = useRef(false)
  const seededStep3 = useRef(false)
  const seededStep4 = useRef(false)

  const runGeneration = useCallback(async (fn: () => Promise<void>) => {
      const id = ++genLock.current
      setLoading(true)
      setError(null)
      try {
        await fn()
      } catch (e) {
        if (genLock.current === id) {
          setError(e instanceof Error ? e.message : 'Something went wrong')
        }
      } finally {
        if (genLock.current === id) setLoading(false)
      }
  }, [])

  // Step 2: title + abstract (once per visit after step 1)
  useEffect(() => {
    if (step !== 2 || !draftRef.current.inventionDescription.trim()) return
    if (seededStep2.current) return
    seededStep2.current = true

    let cancelled = false
    runGeneration(async () => {
      const d = draftRef.current
      const title = d.title.trim() || (await generateTitle(d.inventionDescription))
      const abstract =
        d.abstract.trim() || (await generateAbstract(d.inventionDescription, title))
      if (cancelled) return
      setDraft((prev) => ({
        ...prev,
        title: prev.title.trim() ? prev.title : title,
        abstract: prev.abstract.trim() ? prev.abstract : abstract,
      }))
    })
    return () => {
      cancelled = true
    }
  }, [step, runGeneration])

  // Step 3: technical description
  useEffect(() => {
    if (step !== 3) return
    if (seededStep3.current) return
    seededStep3.current = true

    let cancelled = false
    runGeneration(async () => {
      const text = await generateTechnicalDescription(draftRef.current)
      if (cancelled) return
      setDraft((d) => ({
        ...d,
        technicalDescription: d.technicalDescription.trim() ? d.technicalDescription : text,
      }))
    })
    return () => {
      cancelled = true
    }
  }, [step, runGeneration])

  // Step 4: claims + prior art
  useEffect(() => {
    if (step !== 4) return
    if (seededStep4.current) return
    seededStep4.current = true

    let cancelled = false
    runGeneration(async () => {
      const d = draftRef.current
      let claims = d.claims.trim()
      if (!claims) {
        claims = await generateClaims(d)
        if (cancelled) return
        setDraft((prev) => ({ ...prev, claims }))
      }
      const hits = await searchPriorArt(claims, d.inventionDescription)
      if (cancelled) return
      setDraft((prev) => ({
        ...prev,
        priorArt: prev.priorArt.length ? prev.priorArt : hits,
      }))
    })
    return () => {
      cancelled = true
    }
  }, [step, runGeneration])

  // Step 5: optional backend nudge (figures); local uploads stay client-side until storage exists
  useEffect(() => {
    if (step !== 5) return
    let cancelled = false
    void (async () => {
      await requestDrawingsFromDraft(draftRef.current)
      if (cancelled) return
    })()
    return () => {
      cancelled = true
    }
  }, [step])

  const goNext = async () => {
    setError(null)
    if (step === 1) {
      if (!draft.userInput.trim()) {
        setError('Add a short description of your invention to continue.')
        return
      }
      await runGeneration(async () => {
        seededStep2.current = false
        seededStep3.current = false
        seededStep4.current = false
        const desc = await createInventionDescription(draft.userInput)
        setDraft((d) => ({ ...d, inventionDescription: desc }))
        setStep(2)
      })
      return
    }
    if (step < 6) setStep((s) => s + 1)
  }

  const goBack = () => {
    setError(null)
    if (step > 1) setStep((s) => s - 1)
  }

  const addImages = (files: FileList | null) => {
    if (!files?.length) return
    const next: DraftImage[] = []
    for (let i = 0; i < files.length; i++) {
      const f = files[i]
      if (!f.type.startsWith('image/')) continue
      next.push({
        id: crypto.randomUUID(),
        caption: '',
        previewUrl: URL.createObjectURL(f),
        fileName: f.name,
      })
    }
    if (next.length)
      setDraft((d) => ({ ...d, images: [...d.images, ...next] }))
  }

  const removeImage = (id: string) => {
    setDraft((d) => {
      const img = d.images.find((x) => x.id === id)
      if (img) URL.revokeObjectURL(img.previewUrl)
      return { ...d, images: d.images.filter((x) => x.id !== id) }
    })
  }

  const updateImageCaption = (id: string, caption: string) => {
    setDraft((d) => ({
      ...d,
      images: d.images.map((x) => (x.id === id ? { ...x, caption } : x)),
    }))
  }

  const onSubmitPremium = () =>
    runGeneration(async () => {
      await submitPremiumLawyerReview(draftRef.current)
      setDraft((d) => ({ ...d, premiumLawyerReview: true }))
    })

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col px-4 pb-16 pt-10 sm:px-6 lg:px-8">
      <header className="mb-10 text-center">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-accent">
          Patent draft studio
        </p>
        <h1 className="text-balance text-2xl font-semibold tracking-tight text-white sm:text-3xl">
          From idea to filing-ready draft
        </h1>
        <p className="mx-auto mt-3 max-w-lg text-pretty text-sm text-slate-400">
          Walk through each section, edit freely, then connect your Python services when
          ready.
        </p>
      </header>

      <div className="mb-10">
        <Stepper current={step} labels={STEP_LABELS} />
      </div>

      {error && (
        <div
          className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
          role="alert"
        >
          {error}
        </div>
      )}

      <main className={`${panelClass} flex-1`}>
        {loading && (
          <div className="mb-6 flex items-center gap-3 text-sm text-slate-400">
            <span className="inline-flex h-4 w-4 animate-spin rounded-full border-2 border-accent/30 border-t-accent" />
            Working with placeholder services — swap in your API calls in{' '}
            <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-accent">
              src/services/api.ts
            </code>
          </div>
        )}

        {step === 1 && (
          <section aria-labelledby="s1-title">
            <h2 id="s1-title" className="text-lg font-semibold text-white">
              Describe your invention
            </h2>
            <p className="mt-2 text-sm text-slate-400">
              Plain language is fine. This becomes the source for the formal invention
              description.
            </p>
            <label className="mt-6 block">
              <span className={labelClass}>Your notes</span>
              <textarea
                className={textareaClass}
                placeholder="Problem solved, key components, how it works, what’s novel…"
                value={draft.userInput}
                onChange={(e) => setDraft((d) => ({ ...d, userInput: e.target.value }))}
                rows={8}
              />
            </label>
            {/* TODO: on Continue, replace stub with POST to Python — see createInventionDescription in api.ts */}
          </section>
        )}

        {step === 2 && (
          <section aria-labelledby="s2-title" className="space-y-6">
            <h2 id="s2-title" className="text-lg font-semibold text-white">
              Title & abstract
            </h2>
            <p className="text-sm text-slate-400">
              Generated for you (stub), fully editable. Backend:{' '}
              <code className="text-xs text-accent">draft_gen</code> abstract pass.
            </p>
            <label className="block">
              <span className={labelClass}>Title</span>
              <input
                className={inputClass}
                value={draft.title}
                onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
              />
            </label>
            <label className="block">
              <span className={labelClass}>Abstract</span>
              <textarea
                className={textareaClass}
                value={draft.abstract}
                onChange={(e) => setDraft((d) => ({ ...d, abstract: e.target.value }))}
                rows={10}
              />
            </label>
          </section>
        )}

        {step === 3 && (
          <section aria-labelledby="s3-title">
            <h2 id="s3-title" className="text-lg font-semibold text-white">
              Technical description
            </h2>
            <p className="mt-2 text-sm text-slate-400">
              Field, background, detailed embodiments — refine as needed.
            </p>
            <label className="mt-6 block">
              <span className={labelClass}>Detailed description</span>
              <textarea
                className={textareaClass}
                value={draft.technicalDescription}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, technicalDescription: e.target.value }))
                }
                rows={14}
              />
            </label>
            {/* TODO: wire generateTechnicalDescription to your merged section output */}
          </section>
        )}

        {step === 4 && (
          <section aria-labelledby="s4-title" className="space-y-6">
            <h2 id="s4-title" className="text-lg font-semibold text-white">
              Claims & prior art
            </h2>
            <div className="grid gap-8 lg:grid-cols-2 lg:gap-10">
              <label className="block min-h-0 lg:col-span-1">
                <span className={labelClass}>Claims</span>
                <textarea
                  className={`${textareaClass} min-h-[280px]`}
                  value={draft.claims}
                  onChange={(e) => setDraft((d) => ({ ...d, claims: e.target.value }))}
                />
              </label>
              <div>
                <span className={labelClass}>Prior art</span>
                <ul className="max-h-[min(420px,50vh)] space-y-3 overflow-y-auto rounded-xl border border-white/10 bg-white/[0.03] p-4">
                  {draft.priorArt.length === 0 && (
                    <li className="text-sm text-slate-500">No results yet.</li>
                  )}
                  {draft.priorArt.map((hit) => (
                    <li
                      key={hit.id}
                      className="rounded-lg border border-white/5 bg-white/5 p-4 text-sm"
                    >
                      <p className="font-medium text-slate-200">{hit.title}</p>
                      <p className="mt-2 leading-relaxed text-slate-400">{hit.snippet}</p>
                      {hit.sourceUrl && (
                        <a
                          href={hit.sourceUrl}
                          className="mt-2 inline-block text-xs text-accent hover:underline"
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open source
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-xs text-slate-500">
                  {/* TODO: searchPriorArt → Python search_prior_art / patent_search */}
                  Replace stub results with your retrieval pipeline.
                </p>
              </div>
            </div>
          </section>
        )}

        {step === 5 && (
          <section aria-labelledby="s5-title">
            <h2 id="s5-title" className="text-lg font-semibold text-white">
              Drawings & figures
            </h2>
            <p className="mt-2 text-sm text-slate-400">
              Upload reference sketches locally. Persist to Supabase Storage or your API
              when ready.
            </p>
            <div className="mt-6">
              <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-white/20 bg-white/[0.03] px-6 py-12 transition-colors hover:border-accent/40 hover:bg-accent-dim">
                <span className="text-sm font-medium text-slate-300">
                  Drop images or click to browse
                </span>
                <span className="mt-1 text-xs text-slate-500">PNG, JPG, WebP</span>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  className="sr-only"
                  onChange={(e) => addImages(e.target.files)}
                />
              </label>
            </div>
            {/* TODO: requestDrawingsFromDraft — Python drawing_generator */}
            <ul className="mt-8 grid gap-6 sm:grid-cols-2">
              {draft.images.map((img) => (
                <li
                  key={img.id}
                  className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.04]"
                >
                  <div className="aspect-video bg-black/40">
                    <img
                      src={img.previewUrl}
                      alt={img.fileName}
                      className="h-full w-full object-contain"
                    />
                  </div>
                  <div className="p-4">
                    <input
                      className={`${inputClass} mb-2 text-xs`}
                      placeholder="Figure caption"
                      value={img.caption}
                      onChange={(e) => updateImageCaption(img.id, e.target.value)}
                    />
                    <button
                      type="button"
                      className="text-xs text-rose-300/90 hover:text-rose-200"
                      onClick={() => removeImage(img.id)}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {step === 6 && (
          <section aria-labelledby="s6-title" className="space-y-8">
            <h2 id="s6-title" className="text-lg font-semibold text-white">
              Full review
            </h2>
            <p className="text-sm text-slate-400">
              Final pass before export. Each block stays editable.
            </p>

            {[
              ['Title', 'title', draft.title],
              ['Abstract', 'abstract', draft.abstract],
              ['Technical description', 'technicalDescription', draft.technicalDescription],
              ['Claims', 'claims', draft.claims],
            ].map(([label, key, val]) => (
              <label key={key as string} className="block">
                <span className={labelClass}>{label}</span>
                <textarea
                  className={textareaClass}
                  value={val as string}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, [key as keyof PatentDraftState]: e.target.value }))
                  }
                  rows={key === 'claims' ? 8 : 5}
                />
              </label>
            ))}

            <div className="rounded-xl border border-accent/25 bg-accent-dim p-5">
              <label className="flex cursor-pointer items-start gap-4">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 rounded border-white/20 bg-white/10 text-accent focus:ring-accent"
                  checked={draft.premiumLawyerReview}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, premiumLawyerReview: e.target.checked }))
                  }
                />
                <div>
                  <span className="font-medium text-white">Premium: attorney review</span>
                  <p className="mt-1 text-sm text-slate-400">
                    Queue this draft for a licensed patent practitioner. Hook to billing +
                    Supabase row + notification when you wire production.
                  </p>
                </div>
              </label>
              {draft.premiumLawyerReview && (
                <button
                  type="button"
                  disabled={loading}
                  className="mt-4 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-slate-950 transition-opacity hover:opacity-90 disabled:opacity-50"
                  onClick={onSubmitPremium}
                >
                  Submit for review (stub)
                </button>
              )}
              {/* TODO: submitPremiumLawyerReview + getSupabase() for persistence */}
            </div>
          </section>
        )}
      </main>

      <footer className="mt-8 space-y-4">
        <div className="flex flex-col gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-slate-500">
            {isSupabaseConfigured() ? (
              <span className="text-emerald-400/90">Supabase env loaded</span>
            ) : (
              <>
                Supabase: copy <code className="text-slate-400">frontend/.env.example</code> to{' '}
                <code className="text-slate-400">frontend/.env</code> and set URL + anon key.
              </>
            )}
          </p>
          {isSupabaseConfigured() && (
            <button
              type="button"
              disabled={supabaseSaving}
              className="shrink-0 rounded-lg border border-white/15 px-4 py-2 text-xs font-medium text-slate-200 hover:bg-white/5 disabled:opacity-50"
              onClick={async () => {
                setSupabaseMsg(null)
                setSupabaseSaving(true)
                const r = await saveDraftToSupabase(draftRef.current)
                setSupabaseSaving(false)
                setSupabaseMsg(
                  r.ok ? `Saved draft id ${r.id.slice(0, 8)}…` : r.error,
                )
              }}
            >
              {supabaseSaving ? 'Saving…' : 'Save draft to Supabase'}
            </button>
          )}
        </div>
        {supabaseMsg && (
          <p className="text-center text-xs text-slate-400" role="status">
            {supabaseMsg}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <button
            type="button"
            onClick={goBack}
            disabled={step === 1 || loading}
            className="rounded-xl border border-white/15 px-5 py-2.5 text-sm font-medium text-slate-300 transition-colors hover:border-white/25 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Back
          </button>
          <div className="flex gap-3">
            {step < 6 ? (
              <button
                type="button"
                onClick={() => void goNext()}
                disabled={loading}
                className="rounded-xl bg-accent px-6 py-2.5 text-sm font-semibold text-slate-950 shadow-lg shadow-accent/15 transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                Continue
              </button>
            ) : (
              <button
                type="button"
                className="rounded-xl border border-white/20 px-6 py-2.5 text-sm font-medium text-white hover:bg-white/5"
                onClick={() => {
                  const blob = new Blob(
                    [
                      `TITLE\n\n${draft.title}\n\nABSTRACT\n\n${draft.abstract}\n\nDESCRIPTION\n\n${draft.technicalDescription}\n\nCLAIMS\n\n${draft.claims}`,
                    ],
                    { type: 'text/plain' },
                  )
                  const a = document.createElement('a')
                  a.href = URL.createObjectURL(blob)
                  a.download = 'patent-draft.txt'
                  a.click()
                  URL.revokeObjectURL(a.href)
                }}
              >
                Export .txt
              </button>
            )}
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
