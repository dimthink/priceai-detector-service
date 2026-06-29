# PriceAI detector service integration

This repository is the local PriceAI fork candidate for the API relay detector backend.

## Source

- Upstream: https://github.com/canarybyte/veridrop
- License: AGPL-3.0-or-later
- Runtime: Python 3.10+, FastAPI, `relay-detector`

## Product role

PriceAI keeps the public frontend and evidence presentation in the main site. This service owns the expensive and sensitive detection work:

- receive `base_url`, `api_key`, `model`, `mode`, and protocol;
- run protocol-specific probes for Claude, OpenAI-compatible, and Gemini-compatible APIs;
- persist report JSON and shareable report pages;
- never persist raw API keys.

The PriceAI main site should call this service through `NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL`.

## HTTP contract used by PriceAI

Submit detection:

```bash
curl -X POST "$DETECTOR_URL/api/detect/claude" \
  -F base_url="https://relay.example.com" \
  -F api_key="$TEMP_RELAY_KEY" \
  -F model="claude-3-5-sonnet-20241022" \
  -F mode="standard" \
  -F include_long_context=false
```

Protocol endpoints:

- `POST /api/detect/claude`
- `POST /api/detect/openai`
- `POST /api/detect/gemini`

Poll status:

```bash
curl "$DETECTOR_URL/api/status/{job_id}"
```

Fetch report JSON:

```bash
curl "$DETECTOR_URL/api/result/{job_id}.json"
```

Open report page:

```bash
open "$DETECTOR_URL/r/{job_id}"
```

## Local run

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,web]"
VERIDROP_JOBS_DIR=.local/jobs \
PRICEAI_DETECTOR_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 \
.venv/bin/uvicorn web.server:app --host 127.0.0.1 --port 8017
```

Then set PriceAI:

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=http://127.0.0.1:8017
```

## Fork changes to do next

- Add a restricted CORS policy for `https://priceai.cc`, `https://www.priceai.cc`, and local development.
- Add a PriceAI-branded lightweight JSON endpoint if we want a smaller report payload than Veridrop's public report JSON.
- Add request cost warnings and per-IP throttling tuned for PriceAI traffic.
- Decide whether public reports should stay on the detector domain or be proxied under `priceai.cc/api-transit/detector/report/{id}`.
- Keep AGPL source disclosure visible if this fork is deployed as a network service.
