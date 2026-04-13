# Patent Search App — Discussion Log

## Session: 2026-04-12 — Input Redesign + Claim-Level Similarity Matching

### Input change: query string → full patent JSON

The service input was changed from a bare `query` string to a structured patent JSON:

```json
{
  "title": "...",
  "background": "...",
  "summary": "...",
  "detailed_description": "...",
  "claims": "...",
  "test_mode": false
}
```

The `summary` field is used as the search query (same role as the old `query` string). All other fields except `claims` are stored but not used in the search pipeline. `claims` drives the new claim-matching phase.

---

### New feature: per-claim similarity matching

For each claim in the input patent, the service now finds the top-5 most similar claims across the top-2 search results and returns them in the response.

#### Pipeline (appended after second-pass rerank)

1. **Parse claims** — `parse_claims()` splits the input `claims` field and the fetched claims of the top-2 result patents into individual claims using the regex `r'(?<!\w)(\d+)\.\s'`. Same function is used for both input and result patents.

2. **Embed** — Two batch calls to Cohere `embed-english-v3.0` (one for input claims, one for all result claims pooled from both patents). Vectors are L2-normalised.

3. **Cosine similarity** — Dot product of normalised vectors produces an `(input_claims × result_claims)` similarity matrix. Top-5 result claims per input claim are selected.

4. **LLM scoring** — Cohere `command-r-08-2024` scores each of the 5 candidate pairs on a 0.0–1.0 scale. Prompt: score semantic similarity, return only a number. Temperature 0.0 for determinism.

5. **Sort + return** — Each input claim's top-5 matches are sorted by LLM score descending.

#### Design decision: always run LLM on top-5 (not threshold-gated)

The user proposed: use embeddings first, then LLM only if similarity is "very close". Instead of a fixed cosine threshold (which requires tuning), the implementation always runs LLM on the top-5 embedding candidates. This keeps cost bounded (at most `num_input_claims × 5` LLM calls), avoids threshold tuning, and produces consistent results. The embedding step still serves its purpose — it narrows the field before the expensive LLM step.

#### Output addition

```json
"claim_matches": [
  {
    "input_claim_number": 1,
    "top_matches": [
      {
        "similarity_score": 0.87,
        "patent_url": "https://patents.google.com/patent/...",
        "patent_title": "...",
        "claim_number": 3,
        "claim_text": "A rim comprising..."
      }
    ]
  }
]
```

`claim_text` was added so consumers have the matched claim text inline without needing to cross-reference claim numbers.

---

### Test run results (2026-04-12)

Query: bicycle rim centrifugal debris ejection patent

**`test_mode: true`**
- Returned 1 result: "Voice Appliance" — clearly irrelevant. Expected: test_mode only fetches 10 candidates and shortlists 1, so result quality is not meaningful.
- `claim_matches` empty: the fetched patent's HTML returned no parseable claims.

**`test_mode: false` (full pipeline)**
- Returned 10 results, all old (~1890s–1920s) bicycle patents (e.g. "Propelling mechanism for bicycles", "Bicycle-brake").
- `claim_matches` still empty: same `fetch_full_text` issue — old patent pages have different HTML structure, the `class="claims"` regex returns nothing.

### Identified issues

1. **SerpAPI query quality** — the expanded queries are returning 19th-century patents rather than modern rim/self-cleaning patents. The query expansion or SerpAPI search parameters may need tuning.

2. **`fetch_full_text` fragility** — the regex `class="claims">(.*?)</section>` only works on modern Google Patents HTML. Old patent pages use a different structure. Both top-2 results having empty claims caused `claim_matches` to be empty in both runs.
