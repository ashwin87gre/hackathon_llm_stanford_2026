"""Prior-art search logic — keep free of CLI concerns for reuse in a future HTTP service."""

from __future__ import annotations

import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

# Same OpenAI configuration as drawing_generator: OPENAI_API_KEY, optional OPENAI_MODEL (default gpt-5.4).


class _QueryList(BaseModel):
    """Wrapper so the API returns a JSON object; OpenAI structured output requires an object schema, not a bare array."""

    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(
        description="8–12 diverse patent search strings, 5–15 words each, no near-duplicates",
    )


GENERATE_QUERIES_SYSTEM = """You are a patent search expert.

Given a user's invention description, generate multiple diverse search queries
that would be used to find similar patents.

Your goal is to maximize recall of relevant prior art, not just rephrase the input.

INSTRUCTIONS:
- Generate 8–12 queries total
- Each query should reflect a DIFFERENT perspective of the invention:
  1. Plain-language description
  2. Technical / engineering phrasing
  3. Functional description (what it does)
  4. Component-based description (key parts)
  5. Broader/generalized version
  6. Narrow/specific version
  7. Synonym-based variation
  8. Alternative terminology used in patents
  9. Application/domain-focused phrasing
  10. Mechanism-focused phrasing (how it works)

- Do NOT repeat the same query with minor wording changes
- Use terminology commonly found in patents (e.g., "system", "apparatus", "method", "device")
- Avoid unnecessary filler words
- Keep each query concise (5–15 words)

Fill the structured `queries` field only; no prose outside it.
"""


def _openai_chat() -> ChatOpenAI:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it the same way as for drawing_generator."
        )
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4")
    return ChatOpenAI(model=model, temperature=0.3)


def generate_queries(invention_description: str) -> list[str]:
    """
    Given a free-text invention description, call the OpenAI chat model and return a list of query strings.

    Uses structured output (JSON schema) via LangChain — no manual parsing of markdown or raw text.

    Uses OPENAI_API_KEY and OPENAI_MODEL (defaults to gpt-5.4), matching drawing_generator.
    """
    text = invention_description.strip()
    if not text:
        raise ValueError("invention_description must be non-empty")

    llm = _openai_chat().with_structured_output(_QueryList)
    system_msg = SystemMessage(content=GENERATE_QUERIES_SYSTEM)
    human_msg = HumanMessage(content=text)
    out: _QueryList = llm.invoke([system_msg, human_msg])
    return list(out.queries)


def search_prior_art(invention_description: str, *, limit: int = 10) -> dict[str, Any]:
    """
    Generate LLM search queries from the invention text, print them, then return a stub
    search payload (replace retrieval with patent DB / vector search later).
    """
    queries = generate_queries(invention_description)
    print(queries)

    return {
        "invention_description": invention_description,
        "limit": limit,
        "generated_queries": queries,
        "results": [],
        "note": "stub — wire results to patent APIs using generated_queries",
    }
