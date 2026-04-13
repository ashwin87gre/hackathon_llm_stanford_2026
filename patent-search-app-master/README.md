# Patent Search App

Finds semantically similar patents for a given query. Returns top 10 results with Google Patents URLs and relevance scores.

---

## Prerequisites

- Python 3.10+
- Two API keys:
  - **Cohere** — free at [dashboard.cohere.com](https://dashboard.cohere.com)
  - **SerpAPI** — free tier (100 searches/month) at [serpapi.com](https://serpapi.com)

---

## Setup

**1. Clone the repo**
```bash
git clone git@github.com:snowflake-eng/patent-search-app.git
cd patent-search-app
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Set your API keys**
```bash
export COHERE_API_KEY="your-cohere-key"
export SERPAPI_KEY="your-serpapi-key"
```

---

## Run the server

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:  Application startup complete.
INFO:  Uvicorn running on http://0.0.0.0:8000
```

---

## Search for patents

### Full search (~30s)
```bash
printf '\n========== Step 1 — full search ==========\n'
curl -sS -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"summary": "neural network accelerator chip for edge inference"}'
echo
printf '--- End step 1 output ---\n'
```

### Test mode (~3s, uses minimal API quota)
```bash
printf '\n========== Step 2 — test mode ==========\n'
curl -sS -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"summary": "neural network accelerator chip for edge inference", "test_mode": true}'
echo
printf '--- End step 2 output ---\n'
```

### Example response
```json
{
  "results": [
    {
      "url": "https://patents.google.com/patent/US11176449B1/en",
      "title": "Neural network accelerator hardware-specific division of inference into groups",
      "relevance_score": 0.998
    },
    {
      "url": "https://patents.google.com/patent/US20220358370A1/en",
      "title": "Artificial intelligence inference architecture with hardware acceleration",
      "relevance_score": 0.9754
    }
  ]
}
```

---

## Notes

- Full search fetches 20 patent pages serially — the ~30s latency is expected.
- Use `test_mode: true` when testing the setup; it runs 1 query variant and fetches 1 patent page.
- Empty query returns `400 Bad Request`.
