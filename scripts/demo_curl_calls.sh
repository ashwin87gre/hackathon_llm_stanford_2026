#!/usr/bin/env bash
# Labeled curl demos: each step prints a header, runs curl, then a footer.
# Only one process can bind :8000 — set URLs if services run on different ports.
#
# Examples:
#   PATENT_SEARCH_URL=http://127.0.0.1:8000 ./scripts/demo_curl_calls.sh patent-search
#   DRAFT_URL=http://127.0.0.1:8000 ./scripts/demo_curl_calls.sh draft
#   DRAWING_URL=http://127.0.0.1:8000 ./scripts/demo_curl_calls.sh drawing

set -u

PATENT_SEARCH_URL="${PATENT_SEARCH_URL:-http://127.0.0.1:8000}"
DRAFT_URL="${DRAFT_URL:-http://127.0.0.1:8000}"
DRAWING_URL="${DRAWING_URL:-http://127.0.0.1:8000}"

step_begin() {
  local n=$1
  shift
  printf '\n'
  printf '========== Step %d — %s ==========\n' "$n" "$*"
}

step_end() {
  local n=$1
  printf '--- End step %d output ---\n' "$n"
}

cmd_patent_search() {
  step_begin 1 "Patent Search API — full search (slow; needs COHERE + SERPAPI)"
  curl -sS -X POST "${PATENT_SEARCH_URL}/search" \
    -H "Content-Type: application/json" \
    -d '{"summary": "neural network accelerator chip for edge inference"}'
  echo
  step_end 1

  step_begin 2 "Patent Search API — test mode (faster, lower quota)"
  curl -sS -X POST "${PATENT_SEARCH_URL}/search" \
    -H "Content-Type: application/json" \
    -d '{"summary": "neural network accelerator chip for edge inference", "test_mode": true}'
  echo
  step_end 2
}

cmd_draft() {
  step_begin 1 "Draft section service — POST /generate-section (section: title)"
  curl -sS -X POST "${DRAFT_URL}/generate-section" \
    -H "Content-Type: application/json" \
    -d '{
      "description": "A wearable device that monitors heart rate and transmits data to a smartphone app.",
      "section": "title",
      "prior_sections": {}
    }'
  echo
  step_end 1
}

cmd_drawing() {
  step_begin 1 "Patent drawing API — GET /health"
  curl -sS "${DRAWING_URL}/health"
  echo
  step_end 1

  step_begin 2 "Patent drawing API — POST /generate"
  curl -sS -X POST "${DRAWING_URL}/generate" \
    -H "Content-Type: application/json" \
    -d '{"description": "A system that processes images using a neural network."}'
  echo
  step_end 2
}

usage() {
  printf 'Usage: %s {patent-search|draft|drawing|all}\n' "$(basename "$0")"
  printf 'Env: PATENT_SEARCH_URL DRAFT_URL DRAWING_URL (default http://127.0.0.1:8000)\n'
}

case "${1:-}" in
  patent-search) cmd_patent_search ;;
  draft) cmd_draft ;;
  drawing) cmd_drawing ;;
  all)
    cmd_patent_search
    cmd_draft
    cmd_drawing
    ;;
  *)
    usage
    exit 1
    ;;
esac
