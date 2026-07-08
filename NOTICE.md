# Notice

PriceAI Model Detector is a modified fork of Veridrop:

- Upstream repository: https://github.com/canarybyte/veridrop
- Fork repository: https://github.com/physics-dimension/priceai-detector-service
- License: AGPL-3.0-or-later

The upstream project provides the original relay detector architecture,
protocol-specific detector modules, CLI, FastAPI web service, report model, and
test suite.

PriceAI-specific changes include:

- CORS configuration for `priceai.cc` and `www.priceai.cc`;
- Cloudflare Turnstile validation for public detection submissions;
- OpenAI Responses endpoint routing for PriceAI's model detector UI;
- production deployment defaults for the PriceAI detector service;
- integration documentation for the PriceAI main site;
- PriceAI-facing project documentation and attribution.

The `relay_detector` package name and `veridrop` CLI alias are retained for
compatibility with upstream code, tests, and self-hosted workflows.
