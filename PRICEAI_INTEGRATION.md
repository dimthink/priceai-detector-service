# PriceAI Detector Service Integration

This repository is the standalone PriceAI model detector service. It is kept
separate from the main PriceAI repository so the AGPL detector runtime, upstream
Veridrop attribution, sensitive job execution, and future detector experiments
stay behind a stable HTTP contract.

## Source

- PriceAI detector repository: https://github.com/physics-dimension/priceai-detector-service
- PriceAI main repository: https://github.com/physics-dimension/PriceAI
- Upstream: https://github.com/canarybyte/veridrop
- License: AGPL-3.0-or-later
- Runtime: Python 3.10+, FastAPI, `relay-detector`

## Product Role

PriceAI keeps the public frontend, station context, and evidence presentation
in the main site. This service owns the expensive and sensitive detection work:

- receive `base_url`, `api_key`, `model`, `mode`, and protocol;
- run protocol-specific probes for Claude, OpenAI-compatible, OpenAI Responses,
  and Gemini-compatible APIs;
- persist report JSON and shareable report pages;
- never persist raw API keys;
- reject public detection submissions unless Cloudflare Turnstile passes when
  production verification is configured.

The PriceAI main site calls this service through:

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=https://detector.priceai.cc
```

The user-facing entry remains:

```text
https://priceai.cc/api-transit/detector
```

## HTTP Contract Used By PriceAI

Submit detection:

```bash
curl -X POST "$DETECTOR_URL/api/detect/claude" \
  -F base_url="https://relay.example.com" \
  -F api_key="$TEMP_RELAY_KEY" \
  -F model="claude-sonnet-4-6" \
  -F mode="standard" \
  -F include_long_context=false \
  -F turnstile_token="$TURNSTILE_TOKEN"
```

Protocol endpoints:

- `POST /api/detect/claude`
- `POST /api/detect/openai-chat`
- `POST /api/detect/openai-responses`
- `POST /api/detect/gemini`

Turnstile token field:

- Preferred: `turnstile_token`
- Compatible fallback: `cf-turnstile-response`

If `PRICEAI_TURNSTILE_SECRET_KEY` is set, every detection submission requires a
valid token. Local development can leave the secret blank.

Poll status:

```bash
curl "$DETECTOR_URL/api/status/{job_id}"
```

Fetch report JSON:

```bash
curl "$DETECTOR_URL/api/result/{job_id}.json"
```

Open the service-side report page:

```bash
open "$DETECTOR_URL/r/{job_id}"
```

PriceAI may also render the JSON under its own report shell:

```text
https://priceai.cc/api-transit/detector/reports/{job_id}
```

## Expected Response Shape

Submission success:

```json
{
  "job_id": "abc123",
  "status_url": "/api/status/abc123"
}
```

Finished status:

```json
{
  "job_id": "abc123",
  "protocol": "openai_responses",
  "status": "done",
  "base_url": "https://relay.example.com",
  "target_model": "gpt-5.5",
  "mode": "standard",
  "result_url": "/r/abc123",
  "image_url": "/r/abc123.jpg",
  "json_url": "/api/result/abc123.json"
}
```

The report JSON is the detector evidence payload consumed by the PriceAI report
view. Additive fields are allowed; removing or renaming existing report fields
requires updating the main site parser first.

## Local Run

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,web]"
VERIDROP_JOBS_DIR=.local/jobs \
PRICEAI_DETECTOR_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 \
PRICEAI_TURNSTILE_REQUIRED=false \
.venv/bin/uvicorn web.server:app --host 127.0.0.1 --port 8017
```

Then set PriceAI:

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=http://127.0.0.1:8017
NEXT_PUBLIC_TURNSTILE_SITE_KEY=
```

## Production Environment

Detector service:

```bash
PRICEAI_DETECTOR_CORS_ORIGINS=https://priceai.cc,https://www.priceai.cc
PRICEAI_TURNSTILE_REQUIRED=true
PRICEAI_TURNSTILE_SECRET_KEY=<Cloudflare Turnstile secret>
VERIDROP_JOBS_DIR=/opt/priceai-detector/web_data/jobs
```

PriceAI main site:

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=https://detector.priceai.cc
NEXT_PUBLIC_TURNSTILE_SITE_KEY=<Cloudflare Turnstile site key>
```

## Maintenance Rules

- Keep this repository AGPL and public when it backs a public network service.
- Keep upstream attribution visible in README / NOTICE / package metadata.
- Keep user API keys out of logs, disk, report JSON, and response payloads.
- Treat model authenticity reports as evidence, not merchant endorsement.
- Add new detector families behind protocol-specific modules and tests.
- Keep the PriceAI main site integration stable through the HTTP contract above.
