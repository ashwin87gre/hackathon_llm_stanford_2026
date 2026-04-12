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


def call_claude(system_prompt: str, user_message: str, max_tokens: int = 4096) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def call_gpt(system_prompt: str, user_message: str, max_tokens: int = 4096) -> str:
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=max_tokens,
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


TEST_MAX_TOKENS = 200
TEST_DESCRIPTION_CHARS = 300
TEST_SECTION_CHARS = 150


def _truncate_for_test(description: str, prior_sections: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Truncate inputs for test mode to reduce LLM context and speed up runs."""
    desc = description[:TEST_DESCRIPTION_CHARS]
    prior = {k: v[:TEST_SECTION_CHARS] for k, v in prior_sections.items()}
    return desc, prior


def _rough_generate_and_merge_section(
    section: str,
    description: str,
    prior_sections: dict[str, str],
    test_mode: bool = False,
) -> str:
    """Pass 1: Generate a section with both LLMs in parallel, then merge with Claude."""
    max_tokens = TEST_MAX_TOKENS if test_mode else 4096
    if test_mode:
        description, prior_sections = _truncate_for_test(description, prior_sections)

    system_prompt = GENERATION_PROMPTS[section]
    user_message = build_user_message(description, prior_sections)

    # Run Claude and GPT in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        claude_future = pool.submit(call_claude, system_prompt, user_message, max_tokens)
        gpt_future = pool.submit(call_gpt, system_prompt, user_message, max_tokens)
        claude_draft = claude_future.result()
        gpt_draft = gpt_future.result()

    # Merge with Claude
    merge_prompt = MERGE_PROMPTS[section]
    merge_message = (
        f"## Invention Description\n{description}\n\n"
        f"## Draft A (Claude)\n{claude_draft}\n\n"
        f"## Draft B (GPT)\n{gpt_draft}"
    )
    merged = call_claude(merge_prompt, merge_message, max_tokens)
    return merged


def _refine_section(
    section: str,
    description: str,
    rough_draft: dict[str, str],
    prior_refined: dict[str, str],
    test_mode: bool = False,
) -> str:
    """Pass 2: Refine a section using Claude with full draft context."""
    max_tokens = TEST_MAX_TOKENS if test_mode else 4096
    if test_mode:
        description = description[:TEST_DESCRIPTION_CHARS]
        rough_draft = {k: v[:TEST_SECTION_CHARS] for k, v in rough_draft.items()}
        prior_refined = {k: v[:TEST_SECTION_CHARS] for k, v in prior_refined.items()}

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
    return call_claude(system_prompt, user_message, max_tokens)


def generate_patent_draft(description: str, test_mode: bool = False) -> dict[str, str]:
    """Full two-pass pipeline: generate → merge → refine."""
    mode_tag = " [TEST MODE]" if test_mode else ""

    # === Pass 1: Sequential generation with context building ===
    print(f"=== PASS 1: Generating rough draft (dual-LLM + merge){mode_tag} ===\n")
    rough_draft = {}
    for i, section in enumerate(SECTION_ORDER):
        header = section.replace("_", " ").upper()
        print(f"  Generating {section}...", end=" ", flush=True)
        rough_draft[section] = _rough_generate_and_merge_section(
            section, description, rough_draft, test_mode=test_mode
        )
        print("done.\n")
        print(f"  --- {header} ---")
        print(f"  {rough_draft[section][:500]}...")
        print()
        if i < len(SECTION_ORDER) - 1:
            next_section = SECTION_ORDER[i + 1].replace("_", " ")
            print(f"  Proceeding to next section: {next_section}...\n")

    # === Pass 2: Refinement with full draft context ===
    print(f"\n=== PASS 2: Refining with full draft context (Claude){mode_tag} ===\n")
    final_draft = {}
    for section in SECTION_ORDER:
        print(f"  Refining {section}...", end=" ", flush=True)
        final_draft[section] = _refine_section(
            section, description, rough_draft, final_draft, test_mode=test_mode
        )
        print("done.")

    return final_draft


def format_draft(draft: dict[str, str]) -> str:
    """Format the patent draft for display."""
    parts = []
    for section in SECTION_ORDER:
        header = section.replace("_", " ").upper()
        parts.append(f"{'='*80}\n{header}\n{'='*80}\n\n{draft[section]}\n")
    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    from test_descriptions import TEST_DESCRIPTIONS

    args = sys.argv[1:]
    test_mode = "--test" in args
    args = [a for a in args if a != "--test"]

    idx = int(args[0]) if args else 0
    desc = TEST_DESCRIPTIONS[idx]

    print(f"\nINPUT: {desc[:80]}...\n")
    draft = generate_patent_draft(desc, test_mode=test_mode)
    print(f"\n{format_draft(draft)}")
