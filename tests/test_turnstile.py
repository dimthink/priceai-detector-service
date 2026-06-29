"""Cloudflare Turnstile gate for expensive detector submissions."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
import respx
from fastapi import HTTPException
from starlette.requests import Request

from web import server


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/detect/openai-chat",
        "headers": headers or [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "https",
        "client": ("127.0.0.1", 50000),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_turnstile_disabled_without_secret_allows_local_dev(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("PRICEAI_TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("PRICEAI_TURNSTILE_REQUIRED", raising=False)

    await server._verify_turnstile(_request(), "")


@pytest.mark.asyncio
async def test_turnstile_required_rejects_missing_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRICEAI_TURNSTILE_SECRET_KEY", "secret")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.setenv("PRICEAI_TURNSTILE_REQUIRED", "true")

    with pytest.raises(HTTPException) as exc:
        await server._verify_turnstile(_request(), "")

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_turnstile_success_posts_secret_response_and_client_ip(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("PRICEAI_TURNSTILE_SECRET_KEY", "secret")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("PRICEAI_TURNSTILE_REQUIRED", raising=False)

    async with respx.mock(assert_all_called=True) as router:
        route = router.post(server._TURNSTILE_VERIFY_URL).mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        await server._verify_turnstile(
            _request(headers=[(b"cf-connecting-ip", b"203.0.113.9")]),
            "turnstile-token",
        )

    body = parse_qs(route.calls[0].request.content.decode())
    assert body["secret"] == ["secret"]
    assert body["response"] == ["turnstile-token"]
    assert body["remoteip"] == ["203.0.113.9"]


@pytest.mark.asyncio
async def test_turnstile_rejects_failed_challenge(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRICEAI_TURNSTILE_SECRET_KEY", "secret")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)

    async with respx.mock(assert_all_called=True) as router:
        router.post(server._TURNSTILE_VERIFY_URL).mock(
            return_value=httpx.Response(
                200,
                json={"success": False, "error-codes": ["invalid-input-response"]},
            )
        )

        with pytest.raises(HTTPException) as exc:
            await server._verify_turnstile(_request(), "bad-token")

    assert exc.value.status_code == 403
