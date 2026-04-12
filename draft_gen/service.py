"""REST service for generating a single rough-draft section.

POST /generate-section
  Body: { "description": str, "section": str, "prior_sections": {str: str} }
  Returns: { "section": str, "content": str }

Launch flags:
  python3 service.py           # normal mode
  python3 service.py --test    # test mode: truncated context, 200-token outputs
  TEST_MODE=1 uvicorn service:app  # same via env var
"""

import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from prompts import SECTION_ORDER
from generate_draft import _rough_generate_and_merge_section

TEST_MODE = os.getenv("TEST_MODE", "").lower() in ("1", "true")

app = FastAPI(title="Patent Draft Section Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_SECTIONS = set(SECTION_ORDER)


class GenerateSectionRequest(BaseModel):
    description: str
    section: str
    prior_sections: dict[str, str] = {}


class GenerateSectionResponse(BaseModel):
    section: str
    content: str


@app.post("/generate-section", response_model=GenerateSectionResponse)
def generate_section(req: GenerateSectionRequest):
    if req.section not in VALID_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid section '{req.section}'. Must be one of: {sorted(VALID_SECTIONS)}",
        )

    invalid_prior = set(req.prior_sections) - VALID_SECTIONS
    if invalid_prior:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid keys in prior_sections: {sorted(invalid_prior)}",
        )

    content = _rough_generate_and_merge_section(
        section=req.section,
        description=req.description,
        prior_sections=req.prior_sections,
        test_mode=TEST_MODE,
    )
    return GenerateSectionResponse(section=req.section, content=content)


if __name__ == "__main__":
    import uvicorn
    if "--test" in sys.argv:
        os.environ["TEST_MODE"] = "1"
        # Reload mode spawns a subprocess — env var is inherited
    uvicorn.run("service:app", host="0.0.0.0", port=8000, reload=True)
