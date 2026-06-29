"""HTTP route wiring for OpenAI Responses API detections."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from web import server


def _request(path: str = "/api/detect/openai-responses") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("127.0.0.1", 50000),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_openai_responses_route_submits_separate_protocol(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_preflight(*_args, **_kwargs):
        captured["preflight"] = True

    async def fake_submit(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "job12345"

    monkeypatch.setattr(server, "_preflight_or_422", fake_preflight)
    monkeypatch.setattr(server.jobs, "submit", fake_submit)

    response = await server.api_detect_openai_responses(
        _request(),
        base_url="https://relay.example/v1",
        api_key="sk-test-key",
        model="gpt-5.3-codex",
        mode="standard",
    )

    assert response.status_code == 200
    assert captured["preflight"] is True
    assert captured["kwargs"]["protocol"] == "openai_responses"
    assert captured["kwargs"]["include_long_context"] is False
    assert captured["kwargs"]["include_long_context_extreme"] is False
