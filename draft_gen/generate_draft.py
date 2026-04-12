import os
from concurrent.futures import ThreadPoolExecutor

import anthropic
import openai

from prompts import (
    SECTION_ORDER,
    GENERATION_PROMPTS,
    MERGE_PROMPTS,
    REFINEMENT_PROMPTS,
)


def call_claude(system_prompt: str, user_message: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def call_gpt(system_prompt: str, user_message: str) -> str:
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content


def build_user_message(description: str, prior_sections: dict[str, str]) -> str:
    """Build the user message with invention description and any prior section context."""
    parts = [f"## Invention Description\n{description}"]
    for section_name, section_text in prior_sections.items():
        header = section_name.upper()
        parts.append(f"## {header}\n{section_text}")
    return "\n\n".join(parts)


def generate_and_merge_section(
    section: str,
    description: str,
    prior_sections: dict[str, str],
) -> str:
    """Pass 1: Generate a section with both LLMs in parallel, then merge with Claude."""
    system_prompt = GENERATION_PROMPTS[section]
    user_message = build_user_message(description, prior_sections)

    # Run Claude and GPT in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        claude_future = pool.submit(call_claude, system_prompt, user_message)
        gpt_future = pool.submit(call_gpt, system_prompt, user_message)
        claude_draft = claude_future.result()
        gpt_draft = gpt_future.result()

    # Merge with Claude
    merge_prompt = MERGE_PROMPTS[section]
    merge_message = (
        f"## Invention Description\n{description}\n\n"
        f"## Draft A (Claude)\n{claude_draft}\n\n"
        f"## Draft B (GPT)\n{gpt_draft}"
    )
    merged = call_claude(merge_prompt, merge_message)
    return merged


def refine_section(
    section: str,
    description: str,
    rough_draft: dict[str, str],
    prior_refined: dict[str, str],
) -> str:
    """Pass 2: Refine a section using Claude with full draft context."""
    system_prompt = REFINEMENT_PROMPTS[section]

    parts = [f"## Invention Description\n{description}"]

    # Include the full rough draft for reference
    parts.append("## === ROUGH DRAFT (for reference) ===")
    for s in SECTION_ORDER:
        parts.append(f"### {s.upper()} (rough)\n{rough_draft[s]}")

    # Include any already-refined sections
    if prior_refined:
        parts.append("## === REFINED SECTIONS SO FAR ===")
        for s, text in prior_refined.items():
            parts.append(f"### {s.upper()} (refined)\n{text}")

    # The section to refine
    parts.append(f"## === SECTION TO REFINE ===\n### {section.upper()}\n{rough_draft[section]}")

    user_message = "\n\n".join(parts)
    return call_claude(system_prompt, user_message)


def generate_patent_draft(description: str) -> dict[str, str]:
    """Full two-pass pipeline: generate → merge → refine."""

    # === Pass 1: Sequential generation with context building ===
    print("=== PASS 1: Generating rough draft (dual-LLM + merge) ===\n")
    rough_draft = {}
    for section in SECTION_ORDER:
        print(f"  Generating {section}...", end=" ", flush=True)
        rough_draft[section] = generate_and_merge_section(
            section, description, rough_draft
        )
        print("done.")

    # === Pass 2: Refinement with full draft context ===
    print("\n=== PASS 2: Refining with full draft context (Claude) ===\n")
    final_draft = {}
    for section in SECTION_ORDER:
        print(f"  Refining {section}...", end=" ", flush=True)
        final_draft[section] = refine_section(
            section, description, rough_draft, final_draft
        )
        print("done.")

    return final_draft


def format_draft(draft: dict[str, str]) -> str:
    """Format the patent draft for display."""
    return (
        f"{'='*80}\n"
        f"TITLE\n"
        f"{'='*80}\n\n"
        f"{draft['title']}\n\n"
        f"{'='*80}\n"
        f"ABSTRACT\n"
        f"{'='*80}\n\n"
        f"{draft['abstract']}\n\n"
        f"{'='*80}\n"
        f"DETAILED DESCRIPTION\n"
        f"{'='*80}\n\n"
        f"{draft['description']}\n\n"
        f"{'='*80}\n"
        f"CLAIMS\n"
        f"{'='*80}\n\n"
        f"{draft['claims']}\n"
    )


if __name__ == "__main__":
    import sys
    from test_descriptions import TEST_DESCRIPTIONS

    if len(sys.argv) > 1:
        idx = int(sys.argv[1])
        descriptions = [TEST_DESCRIPTIONS[idx]]
    else:
        descriptions = [TEST_DESCRIPTIONS[0]]

    for desc in descriptions:
        print(f"\nINPUT: {desc[:80]}...\n")
        draft = generate_patent_draft(desc)
        print(f"\n{format_draft(draft)}")
