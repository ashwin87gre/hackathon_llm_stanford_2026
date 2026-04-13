from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from patent_search import search_patents, PatentResult, ClaimMatch

app = FastAPI(title="Patent Search API")


class SearchRequest(BaseModel):
    title: str = ""
    background: str = ""
    summary: str
    detailed_description: str = ""
    claims: str = ""
    test_mode: bool = False


class SearchResponse(BaseModel):
    results: list[PatentResult]
    claim_matches: list[ClaimMatch] = []


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    if not req.summary.strip():
        raise HTTPException(status_code=400, detail="summary must not be empty")
    results, claim_matches = search_patents(req.summary, input_claims_text=req.claims, test_mode=req.test_mode)
    return SearchResponse(results=results, claim_matches=claim_matches)
