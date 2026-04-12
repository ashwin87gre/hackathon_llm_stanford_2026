"""
CLI entry for prior-art search — standalone; service layer will call `prior_art.search_prior_art`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python /path/to/search_prior_art/main.py` (cwd need not be this folder)
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prior_art import search_prior_art

# Built-in sample for `python main.py --test`
SAMPLE_INVENTION = (
    "Wearable sensor that estimates blood glucose non-invasively using optical "
    "spectroscopy and a lightweight on-device classifier, with alerts via Bluetooth."
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search prior art (standalone; service wrapper can call search_prior_art())",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run search_prior_art with a brief built-in invention description",
    )
    parser.add_argument(
        "invention_description",
        nargs="?",
        default="",
        help="Invention description for query generation (optional; stdin if piped)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Max number of results to return (stub)",
    )
    args = parser.parse_args()

    if args.test:
        text = SAMPLE_INVENTION
    else:
        text = args.invention_description.strip()
        if not text and not sys.stdin.isatty():
            text = sys.stdin.read().strip()

        if not text:
            parser.error("provide --test, an invention description argument, or pipe text on stdin")

    search_prior_art(text, limit=args.limit)


if __name__ == "__main__":
    main()
