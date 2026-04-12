"""
Future HTTP service boundary: import `search_prior_art` from `prior_art` and expose e.g.
POST /search with JSON `{"query": "...", "limit": 10}`.
"""

from prior_art import generate_queries, search_prior_art

__all__ = ["generate_queries", "search_prior_art"]
