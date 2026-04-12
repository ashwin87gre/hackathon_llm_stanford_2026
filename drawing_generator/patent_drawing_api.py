"""
HTTP **service** for the patent drawing pipeline: run this process and leave it running;
it listens for HTTP requests until you stop it (Ctrl+C).

From ``drawing_generator/`` (set ``OPENAI_API_KEY`` or Claude key first)::

  python patent_drawing_api.py

Equivalent::

  uvicorn patent_drawing_api:app --host 0.0.0.0 --port 8000

Then in another terminal::

  curl -s -X POST "http://127.0.0.1:8000/generate" \\
    -H "Content-Type: application/json" \\
    -d '{"description": "A system that processes images using a neural network."}'

Swagger UI: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from patent_drawing_service import LLMProvider, run_patent_drawing_from_dict

app = FastAPI(title="Patent drawing generator", version="0.1.0")


class PatentDrawingRequest(BaseModel):
    """Body: at minimum ``description``; optional metadata for the pipeline."""

    description: str = Field(..., min_length=1, description="Invention / patent description text")
    invention_name: str = ""
    key_innovation: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate")
def generate(
    body: PatentDrawingRequest,
    provider: LLMProvider = Query(
        "openai",
        description="LLM backend: openai (OPENAI_API_KEY) or claude (ANTHROPIC_API_KEY / CLAUDE_API_KEY)",
    ),
) -> dict[str, str]:
    try:
        return run_patent_drawing_from_dict(
            description=body.description,
            invention_name=body.invention_name,
            key_innovation=body.key_innovation,
            provider=provider,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
