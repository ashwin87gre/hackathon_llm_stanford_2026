# Patent Search App — Decisions & Discussion Log

## Goal
Build a hackathon app that takes a phrase describing a patent and returns semantically similar patents ranked by similarity score. Top 10 results, each with a patent URL and score.

## API Choice: SerpAPI + Google Patents (3rd iteration)
- **1st choice: Patentsview** — free, no API key, but went down for infrastructure maintenance
- **2nd choice: Lens.org** — great API but token approval process takes time (not viable for hackathon)
- **3rd choice: SerpAPI + Google Patents** (current):
  - Instant API key, 100 free searches/month at serpapi.com
  - Searches Google Patents — broad global coverage
  - Returns title, snippet (abstract excerpt), publication_number, direct Google Patents URL
  - Simple GET API, no complex auth flow
  - **Limitation**: returns snippets not full abstracts/claims, so reranking has less text to work with
  - Patent URLs: direct `patents.google.com` links from the response

## Ranking: Cross-Encoder Reranking over Cosine Similarity

### Problem with naive embedding + cosine similarity
Patent abstracts are full of boilerplate legal language ("the present invention relates to", "comprising", "wherein") that dominates embedding vectors. Many unrelated patents end up with high cosine similarity simply because they share this legal phrasing.

### Solution: Cohere Rerank (cross-encoder)
- A **bi-encoder** (embed separately → cosine sim) compresses each text into a fixed vector independently — subtle distinctions get lost in the noise of shared legal terms.
- A **cross-encoder** (Cohere `rerank-english-v3.0`) processes the (query, document) pair together, so it can attend to fine-grained relevance signals that bi-encoders miss.
- Trade-off: cross-encoders are slower (can't pre-compute), but since we only rerank ~50 candidates, latency is fine.

### Two-pass reranking with full claims
SerpAPI only returns snippets, but we need full claims for accurate ranking. Solution: two-pass approach.

1. **First pass**: rerank all ~100 candidates using title + snippet → narrow to top 20
2. **Fetch full text**: scrape Google Patents HTML for those 20 patents (abstract + claims)
3. **Second pass**: rerank the 20 using title + full abstract + full claims → final top 10

This gives us rich claim text for the cross-encoder without fetching 100 patent pages.

**Observed improvement**: CRISPR query went from a sharp 0.97→0.01 score cliff (snippet-only) to a smooth 0.99→0.97→0.89→0.20 curve (full claims). Several relevant patents that were missed with snippets now appear in top 10.

## Query Expansion (multi-query retrieval)

### Problem
Keyword search is the recall bottleneck. If the user says "detecting objects in images" but a relevant patent uses "visual recognition of entities", the keyword match misses it and the cross-encoder never sees it.

### Solution
Use Cohere `command-r-08-2024` to generate 3 alternative phrasings of the original query with different technical terminology. Each variant hits SerpAPI/Google Patents separately. Results are deduplicated by publication_number before reranking.

### Key design decisions
- **Original query is always included** — variants are additive, never replace the user's phrasing.
- **Reranking still uses the original query** — the variants are only for casting a wider retrieval net. The user's original phrasing best represents their intent.
- **Budget split**: 25 results per query variant (4 queries × 25 = up to 100 candidates, deduplicated) instead of 50 from a single query. More diverse pool.
- **Trade-off**: adds ~1-2 seconds for the LLM call, but significantly better recall.

### Why not expand for reranking too?
The cross-encoder already handles synonyms and paraphrasing well — it sees both texts together. Expanding the query helps *find* candidates, but the reranker doesn't need the help.

## Architecture

```
Input phrase (string)
  → Cohere command-r-08-2024 generates 3 query variants
  → Each variant (+ original) hits SerpAPI Google Patents search (25 each)
  → Deduplicate by publication_number
  → First-pass rerank: title + snippet → top 20
  → Fetch full abstract + claims from Google Patents HTML for top 20
  → Second-pass rerank: title + abstract + claims → top 10
  → Return top 10 with Google Patents URLs + relevance scores
```

## Dependencies
- `cohere` — query expansion (command-r-08-2024), reranking API
- `requests` — HTTP calls to SerpAPI

## Environment Variables
- `COHERE_API_KEY` — Cohere API key (free trial at dashboard.cohere.com)
- `SERPAPI_KEY` — SerpAPI key (instant, 100 free searches/month at serpapi.com)

## Service Runtime — Observed End-to-End Run

Verified with query: `"neural network accelerator chip for edge inference"`

### Startup
FastAPI + Uvicorn start, `POST /search` route registered. Ready in <1s.

### Request → Response flow

| Step | What happens | Where in code |
|------|-------------|---------------|
| 1 | HTTP `POST /search` received, body validated against `SearchRequest`. Empty query → 400. | `server.py:17` |
| 2 | Cohere `command-r-08-2024` expands original query into 3 variants with different terminology. Original is always kept. | `patent_search.py:14` |
| 3 | Each of 4 queries hits SerpAPI `google_patents` engine (25 results each). Deduplicated by `publication_number` → ≤100 unique candidates. | `patent_search.py:69` |
| 4 | First-pass rerank: Cohere `rerank-english-v3.0` scores all candidates using title + snippet. Top 20 kept. | `patent_search.py:145` |
| 5 | Full-text fetch: 20 serial HTTP GETs to `patents.google.com`, regex-extracts abstract and claims from HTML. | `patent_search.py:88` |
| 6 | Second-pass rerank: Cohere reranks the 20 using title + abstract + claims. Top 10 returned. | `patent_search.py:163` |
| 7 | `200 OK` with `{"results": [...]}` — 10 patents with URLs and relevance scores. | `server.py:21` |

### Observed latency breakdown
- Total: **~31 seconds**
- Step 5 (serial full-text scraping of 20 patents): **~28s** — dominant bottleneck
- Cohere API calls (expansion + 2× rerank): **~2–3s**

### Sample output (top 3 of 10)
```json
{"url": "https://patents.google.com/patent/US11176449B1/en",
 "title": "Neural network accelerator hardware-specific division of inference into groups…",
 "relevance_score": 0.998}
{"url": "https://patents.google.com/patent/US20220358370A1/en",
 "title": "Artificial intelligence inference architecture with hardware acceleration",
 "relevance_score": 0.9754}
{"url": "https://patents.google.com/patent/US20240161474A1/en",
 "title": "Neural Network Inference Acceleration Method, Target Detection Method…",
 "relevance_score": 0.9585}
```

### Identified optimization opportunity
Step 5 fetches 20 patent pages serially. Parallelizing with `ThreadPoolExecutor` would cut the ~28s scraping time to roughly `28s / 20 workers ≈ 2–3s`, bringing total latency down from ~31s to ~5–6s.

## Test Mode

### Problem
Running the full pipeline (4 query variants × 25 results + 20 full-text fetches) takes ~31s and burns SerpAPI quota. Too slow and expensive for iterating during development.

### Solution
Added `test_mode: bool = False` to the `SearchRequest` body. When `true`:
- Skips query expansion — uses only the original query (1 instead of 4)
- Fetches 10 results from SerpAPI (their `google_patents` minimum; 5 returns a 400)
- First-pass rerank shortlists to 1 patent instead of 20
- Only 1 full-text fetch instead of 20

### Result
~3s end-to-end vs ~31s in full mode. Good enough to verify the pipeline is wired up correctly.

### Implementation note
SerpAPI's `google_patents` engine rejects `num < 10` with a 400. The minimum for test mode is therefore 10, not 5.

### Usage
```json
POST /search
{"query": "your query here", "test_mode": true}
```

| Parameter | Normal | `test_mode: true` |
|---|---|---|
| Query variants | 4 | 1 |
| SerpAPI results per query | 25 | 10 |
| Full-text fetches | 20 | 1 |
| Typical latency | ~31s | ~3s |
