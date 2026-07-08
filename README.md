# PriceAI Model Detector

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

PriceAI Model Detector is the standalone model authenticity and API relay
quality detector used by [PriceAI](https://priceai.cc/api-transit/detector).
It accepts a relay `base_url`, temporary `api_key`, model name, protocol, and
mode, then runs protocol-specific probes for Claude, OpenAI-compatible, OpenAI
Responses, and Gemini-compatible APIs.

This repository is forked from
[canarybyte/veridrop](https://github.com/canarybyte/veridrop), keeps the
AGPL-3.0-or-later license, and preserves upstream attribution. PriceAI-specific
changes include CORS for `priceai.cc`, OpenAI Responses routing, Cloudflare
Turnstile validation, deployment defaults, and an integration contract for the
PriceAI main site.

## Product Boundary

PriceAI keeps the public comparison experience, station context, and report
presentation under the main repository:

- PriceAI main site: https://priceai.cc/api-transit/detector
- PriceAI main repository: https://github.com/physics-dimension/PriceAI

This repository owns the sensitive and expensive execution layer:

- receive `base_url`, `api_key`, `model`, `mode`, and protocol;
- run protocol-specific probes against the user-provided relay;
- persist report JSON and shareable report pages;
- avoid persisting raw API keys;
- enforce Turnstile and rate limits when production verification is configured.

The main site calls this service through
`NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL`.

## Supported Protocols

| Protocol | Endpoint | Detection level |
| --- | --- | --- |
| Claude / Anthropic Messages | `POST /api/detect/claude` | Cryptographic when thinking signature is available |
| OpenAI Chat Completions | `POST /api/detect/openai-chat` | Behavioral / protocol level |
| OpenAI Responses | `POST /api/detect/openai-responses` | Behavioral / protocol level |
| Gemini via OpenAI-compatible API | `POST /api/detect/gemini` | Protocol level |

Report and status endpoints:

```text
GET /api/status/{job_id}
GET /api/result/{job_id}.json
GET /r/{job_id}
GET /r/{job_id}.jpg
```

See [PRICEAI_INTEGRATION.md](PRICEAI_INTEGRATION.md) for the exact HTTP
contract used by the PriceAI frontend.

## Local Run

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,web]"
VERIDROP_JOBS_DIR=.local/jobs \
PRICEAI_DETECTOR_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 \
PRICEAI_TURNSTILE_REQUIRED=false \
.venv/bin/uvicorn web.server:app --host 127.0.0.1 --port 8017
```

Then point a local PriceAI checkout at the service:

```bash
NEXT_PUBLIC_TRANSIT_DETECTOR_API_BASE_URL=http://127.0.0.1:8017
NEXT_PUBLIC_TURNSTILE_SITE_KEY=
```

## CLI

The upstream CLI is kept for detector development and self-hosted testing:

```bash
.venv/bin/relay-detector ping --model claude-haiku-4-5
.venv/bin/relay-detector detect --model claude-haiku-4-5 --mode standard -o out/test.json
.venv/bin/relay-detector compare out/test.json
```

`veridrop` remains as a compatibility command alias.

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

## Architecture

```text
src/relay_detector/
  core/                 protocol-neutral runner, scorer, models, detector base
  protocols/
    anthropic/          Claude / Anthropic detectors
    openai/             OpenAI Chat Completions and Responses detectors
    gemini/             Gemini OpenAI-compatible detectors
web/
  server.py             FastAPI routes and PriceAI integration endpoints
  jobs.py               in-process async job queue and report persistence
  probe.py              pre-submit model list and model-alive probes
  image_report.py       report image renderer
tests/                  pytest coverage for detector and web behavior
```

The package name is still `relay_detector` to keep upstream compatibility and
reduce merge friction. Future PriceAI-specific modules should be introduced
behind stable adapters instead of mixing product policy into protocol detectors.

## Privacy And Safety

- Raw API keys should live only in memory for the active job.
- Reports store masked API keys only.
- Production submissions should require Turnstile.
- Public report pages are evidence artifacts, not merchant endorsements.
- Detection consumes the user's relay quota; high-cost probes should stay
  explicit and opt-in.

## Upstream Attribution

This project is based on
[canarybyte/veridrop](https://github.com/canarybyte/veridrop). See
[NOTICE.md](NOTICE.md) for attribution and fork notes.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).

If this service is operated over a network, make the corresponding source for
the running modified version available to users, as required by AGPL section 13.
