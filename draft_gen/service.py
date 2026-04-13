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
from pathlib import Path

from dotenv import load_dotenv

# Load `draft_gen/.env` regardless of current working directory.
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from prompts import SECTION_ORDER
from generate_draft import _rough_generate_and_merge_section

TEST_MODE = os.getenv("TEST_MODE", "").lower() in ("1", "true")

app = FastAPI(title="Patent Draft Section Generator")
# Local dev: allow any origin so Vite (any host/port) always gets CORS headers.
# For a public deploy, replace with an explicit allow_origins list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        if not os.getenv(key, "").strip():
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Missing {key}. Copy draft_gen/.env.example to draft_gen/.env "
                    "and set your keys, or set the variable in your shell (PowerShell: "
                    f'$env:{key} = "…").'
                ),
            )

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
