import os
import re
import requests
import cohere
import numpy as np
from pydantic import BaseModel


class PatentResult(BaseModel):
    url: str
    title: str
    relevance_score: float


class ClaimSimilarity(BaseModel):
    similarity_score: float
    patent_url: str
    patent_title: str
    claim_number: int
    claim_text: str


class ClaimMatch(BaseModel):
    input_claim_number: int
    top_matches: list[ClaimSimilarity]


def expand_query(co: cohere.Client, query: str, n_variants: int = 3) -> list[str]:
    """
    Generate variant phrasings of the query to improve keyword recall.

    Different patents describe the same concept with different terminology.
    Expanding into multiple phrasings catches patents that keyword search
    would otherwise miss.
    """
    response = co.chat(
        message=(
            f"Generate {n_variants} alternative phrasings of this patent search query. "
            f"Use different technical terminology and synonyms each time. "
            f"Return ONLY the phrasings, one per line, no numbering or extra text.\n\n"
            f"Query: {query}"
        ),
        model="command-r-08-2024",
        temperature=0.7,
    )
    variants = [line.strip() for line in response.text.strip().splitlines() if line.strip()]
    return [query] + variants[:n_variants]


def fetch_candidates(query: str, limit: int = 25) -> list[dict]:
    """Fetch candidate patents from Google Patents via SerpAPI."""
    response = requests.get(
        "https://serpapi.com/search",
        params={
            "engine": "google_patents",
            "q": query,
            "num": limit,
            "api_key": os.environ["SERPAPI_KEY"],
        },
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("organic_results") or []

    patents = []
    for r in results:
        patent_id = r.get("publication_number", "")
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        patent_link = r.get("patent_link", "")

        if snippet:
            patents.append({
                "patent_id": patent_id,
                "title": title,
                "snippet": snippet,
                "url": patent_link,
            })

    return patents


def fetch_candidates_multi(queries: list[str], per_query: int = 25) -> list[dict]:
    """
    Fetch candidates for multiple query variants and deduplicate by patent_id.

    Spreads the budget across queries so we get diverse candidates
    without blowing up the total count.
    """
    seen_ids = set()
    all_candidates = []
    for q in queries:
        candidates = fetch_candidates(q, limit=per_query)
        for p in candidates:
            pid = p["patent_id"]
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_candidates.append(p)
    return all_candidates


def fetch_full_text(patent_url: str) -> dict[str, str]:
    """
    Fetch full abstract and claims from a Google Patents page.

    Returns {"abstract": ..., "claims": ...} with HTML tags stripped.
    """
    try:
        resp = requests.get(patent_url, timeout=10)
        resp.raise_for_status()
        html = resp.text
    except requests.RequestException:
        return {"abstract": "", "claims": ""}

    abstract = ""
    abs_match = re.search(r'class="abstract">(.*?)</div>', html, re.DOTALL)
    if abs_match:
        abstract = re.sub(r"<[^>]+>", " ", abs_match.group(1)).strip()

    claims = ""
    claims_match = re.search(r'class="claims">(.*?)</section>', html, re.DOTALL)
    if claims_match:
        claims = re.sub(r"<[^>]+>", " ", claims_match.group(1)).strip()
        # Collapse whitespace
        claims = re.sub(r"\s+", " ", claims)

    return {"abstract": abstract, "claims": claims}


def build_document_snippet(patent: dict) -> str:
    """Build a document from title + snippet for first-pass reranking."""
    title = patent.get("title", "")
    snippet = patent.get("snippet", "")
    return f"{title}\n\n{snippet}".strip()


def build_document_full(patent: dict) -> str:
    """Build a document from title + abstract + claims for second-pass reranking."""
    title = patent.get("title", "")
    abstract = patent.get("abstract", "")
    claims = patent.get("claims", "")
    body = f"{abstract}\n\n{claims}" if claims else abstract
    return f"{title}\n\n{body}".strip()


def parse_claims(claims_text: str) -> list[str]:
    """Split a claims block into individual claims by numbered markers (1., 2., ...)."""
    parts = re.split(r'(?<!\w)(\d+)\.\s', claims_text.strip())
    # re.split with a capturing group interleaves [pre, num, text, num, text, ...]
    claims = []
    i = 1
    while i + 1 < len(parts):
        claim_text = parts[i + 1].strip()
        if claim_text:
            claims.append(claim_text)
        i += 2
    return claims


def embed_texts(co: cohere.Client, texts: list[str]) -> np.ndarray:
    """Return an (N, D) matrix of L2-normalised embeddings for the given texts."""
    response = co.embed(texts=texts, model="embed-english-v3.0", input_type="search_document")
    vecs = np.array(response.embeddings, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-9)


def score_claim_pair_llm(co: cohere.Client, input_claim: str, result_claim: str) -> float:
    """Ask an LLM to score semantic similarity between two patent claims (0.0–1.0)."""
    response = co.chat(
        message=(
            "Score the semantic similarity between these two patent claims on a scale of 0.0 to 1.0, "
            "where 1.0 means they cover the same inventive concept and 0.0 means completely unrelated. "
            "Return ONLY a decimal number, nothing else.\n\n"
            f"Claim A: {input_claim}\n\nClaim B: {result_claim}"
        ),
        model="command-r-08-2024",
        temperature=0.0,
    )
    try:
        return round(float(response.text.strip()), 4)
    except ValueError:
        return 0.0


def match_claims(
    co: cohere.Client,
    input_claims: list[str],
    top_2_patents: list[dict],
) -> list[ClaimMatch]:
    """
    For each input claim, find the top-5 most similar claims across the top-2 result patents.

    Two-pass: cosine similarity on embeddings narrows to top-5, then LLM scores those 5.
    """
    # Build flat list of result claims: (patent_dict, 1-based claim_number, claim_text)
    result_claim_entries: list[tuple[dict, int, str]] = []
    for patent in top_2_patents:
        for idx, claim_text in enumerate(parse_claims(patent.get("claims", "")), start=1):
            result_claim_entries.append((patent, idx, claim_text))

    if not result_claim_entries or not input_claims:
        return []

    result_texts = [entry[2] for entry in result_claim_entries]

    # Embed all claims in two batch calls
    input_vecs = embed_texts(co, input_claims)   # (I, D)
    result_vecs = embed_texts(co, result_texts)  # (R, D)

    # Cosine similarity matrix (I, R) — vectors are already L2-normalised
    sim_matrix = input_vecs @ result_vecs.T

    claim_matches = []
    for i, input_claim in enumerate(input_claims):
        scores = sim_matrix[i]  # (R,)
        top5_indices = np.argsort(scores)[::-1][:5]

        top_matches = []
        for r_idx in top5_indices:
            patent, claim_number, result_claim = result_claim_entries[r_idx]
            llm_score = score_claim_pair_llm(co, input_claim, result_claim)
            top_matches.append(ClaimSimilarity(
                similarity_score=llm_score,
                patent_url=patent["url"],
                patent_title=patent["title"],
                claim_number=claim_number,
                claim_text=result_claim,
            ))

        top_matches.sort(key=lambda x: x.similarity_score, reverse=True)
        claim_matches.append(ClaimMatch(
            input_claim_number=i + 1,
            top_matches=top_matches,
        ))

    return claim_matches


def search_patents(
    query: str,
    top_k: int = 10,
    test_mode: bool = False,
    input_claims_text: str = "",
) -> tuple[list[PatentResult], list[ClaimMatch]]:
    co = cohere.Client(os.environ["COHERE_API_KEY"])

    # test_mode: skip query expansion, fetch only 5 candidates, shortlist 1 for full-text fetch
    if test_mode:
        queries = [query]
        per_query = 10  # SerpAPI google_patents engine minimum is 10
        first_pass_top_n = 1
    else:
        queries = expand_query(co, query)
        per_query = 25
        first_pass_top_n = 20

    # Step 1: Fetch candidates (single query in test_mode, 4 variants otherwise)
    candidates = fetch_candidates_multi(queries, per_query=per_query)
    if not candidates:
        return [], []

    # Step 2: First-pass rerank using snippets to narrow the field
    snippet_docs = [build_document_snippet(p) for p in candidates]
    first_pass = co.rerank(
        query=query,
        documents=snippet_docs,
        model="rerank-english-v3.0",
        top_n=min(first_pass_top_n, len(candidates)),
    )

    # Step 3: Fetch full abstract + claims for shortlisted candidates
    shortlist = []
    for r in first_pass.results:
        patent = candidates[r.index].copy()
        full_text = fetch_full_text(patent["url"])
        patent["abstract"] = full_text["abstract"]
        patent["claims"] = full_text["claims"]
        shortlist.append(patent)

    # Step 4: Second-pass rerank using full text
    full_docs = [build_document_full(p) for p in shortlist]
    second_pass = co.rerank(
        query=query,
        documents=full_docs,
        model="rerank-english-v3.0",
        top_n=min(top_k, len(shortlist)),
    )

    results = [
        PatentResult(
            url=shortlist[r.index]["url"],
            title=shortlist[r.index]["title"],
            relevance_score=round(r.relevance_score, 4),
        )
        for r in second_pass.results
    ]

    claim_matches: list[ClaimMatch] = []
    if input_claims_text.strip():
        top_2_patents = [shortlist[r.index] for r in second_pass.results[:2]]
        input_claims = parse_claims(input_claims_text)
        if input_claims:
            claim_matches = match_claims(co, input_claims, top_2_patents)

    return results, claim_matches


if __name__ == "__main__":
    import sys
    from test_queries import TEST_QUERIES

    # Optional: pass indices as args to run specific queries (e.g. python patent_search.py 0 3 5)
    if len(sys.argv) > 1:
        indices = [int(i) for i in sys.argv[1:]]
        queries = [TEST_QUERIES[i] for i in indices]
    else:
        queries = TEST_QUERIES

    for i, query in enumerate(queries):
        print(f"{'='*80}")
        print(f"[{TEST_QUERIES.index(query)}] QUERY: {query}")
        print(f"{'='*80}\n")
        results = search_patents(query)
        if not results:
            print("  No results found.\n")
            continue
        for r in results:
            print(f"  {r.relevance_score:.4f}  {r.title}")
            print(f"           {r.url}\n")
        print()
