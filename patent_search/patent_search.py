import os
import requests
import cohere
from dataclasses import dataclass


@dataclass
class PatentResult:
    url: str
    title: str
    relevance_score: float


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


def build_document(patent: dict) -> str:
    """
    Build a reranking document from title + snippet.

    SerpAPI returns a snippet (abstract excerpt) rather than full claims.
    We combine title + snippet for the best signal available.
    """
    title = patent.get("title", "")
    snippet = patent.get("snippet", "")
    return f"{title}\n\n{snippet}".strip()


def search_patents(query: str, top_k: int = 10) -> list[PatentResult]:
    co = cohere.Client(os.environ["COHERE_API_KEY"])

    # Step 1: Expand query into multiple phrasings for better keyword recall
    queries = expand_query(co, query)

    # Step 2: Fetch candidates across all query variants, deduplicated
    candidates = fetch_candidates_multi(queries, per_query=25)
    if not candidates:
        return []

    # Step 3: Build documents from title + snippet
    documents = [build_document(p) for p in candidates]

    # Step 4: Rerank using a cross-encoder (still uses original query)
    rerank_response = co.rerank(
        query=query,
        documents=documents,
        model="rerank-english-v3.0",
        top_n=top_k,
    )

    return [
        PatentResult(
            url=candidates[r.index]["url"],
            title=candidates[r.index]["title"],
            relevance_score=round(r.relevance_score, 4),
        )
        for r in rerank_response.results
    ]


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
