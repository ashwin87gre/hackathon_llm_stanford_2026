"""
Patent drawing pipeline as a service: invention JSON file in → structured JSON out.

Output keys:
  drawing_url — diagrams.net link for the block diagram
  brief_description_of_drawings — LLM-generated "Brief Description of the Drawings" text
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Literal, TypedDict

from invention_components import (
    diagrams_net_create_url,
    invoke_patent_drawing_pipeline,
    load_invention,
    set_llm_provider,
)

LLMProvider = Literal["openai", "claude"]


class PatentDrawingServiceResult(TypedDict):
    drawing_url: str
    brief_description_of_drawings: str


def _result_from_final(final: dict) -> PatentDrawingServiceResult:
    return {
        "drawing_url": diagrams_net_create_url(final["drawio_xml"]),
        "brief_description_of_drawings": final["brief_description_drawings"],
    }


def run_patent_drawing_from_dict(
    *,
    description: str,
    invention_name: str = "",
    key_innovation: str = "",
    provider: LLMProvider = "openai",
) -> PatentDrawingServiceResult:
    """
    Run the pipeline from in-memory fields (no file). ``description`` is required; other fields default to "".
    """
    data = {
        "invention_name": invention_name or "",
        "description": description,
        "key_innovation": key_innovation or "",
    }
    set_llm_provider(provider)
    final = invoke_patent_drawing_pipeline(data)
    return _result_from_final(final)


def run_patent_drawing_service(
    patent_description_path: str,
    *,
    provider: LLMProvider = "openai",
) -> PatentDrawingServiceResult:
    """
    Load a patent description JSON file, run the full pipeline, return URL + brief description of drawings.

    The file must contain: invention_name, description, key_innovation (see ``load_invention``).
    """
    set_llm_provider(provider)
    data = load_invention(patent_description_path)
    final = invoke_patent_drawing_pipeline(data)
    return _result_from_final(final)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patent drawing service: outputs JSON with drawing_url and brief_description_of_drawings",
    )
    parser.add_argument(
        "patent_json",
        help="Path to JSON with invention_name, description, key_innovation",
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "claude"),
        default="openai",
        help="LLM backend (same env vars as invention_components.py)",
    )
    args = parser.parse_args()
    try:
        result = run_patent_drawing_service(args.patent_json, provider=args.provider)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
