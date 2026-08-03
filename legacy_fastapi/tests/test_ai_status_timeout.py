import time

import httpx

from app import config
from app.main import app
from app.services import ai_analysis


async def test_ai_status_bounded_by_timeout_even_if_provider_is_slow(monkeypatch):
    """A provider whose API call is slow (or hanging) must not stall the
    whole /api/ai/status response past our own hard timeout backstop.

    Uses httpx.AsyncClient directly (instead of Starlette's TestClient) so
    the test measures the actual response latency, not TestClient's
    per-call event-loop teardown (which blocks on
    `loop.shutdown_default_executor()` until every executor thread —
    including an abandoned slow one — finishes; that teardown delay never
    happens against a real long-running uvicorn server).
    """
    monkeypatch.setattr(ai_analysis, "_PROVIDER_ORDER", ["anthropic"])
    monkeypatch.setattr(ai_analysis, "_provider_key", lambda p: "fake-key")
    monkeypatch.setattr(config, "AI_REQUEST_TIMEOUT_SECONDS", 1)

    def slow_check(provider):
        time.sleep(8)  # longer than our hard timeout (1 + 5 = 6s), but finite
        return {"provider": provider, "usable": True}

    monkeypatch.setattr(ai_analysis, "check_provider", slow_check)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = time.time()
        res = await client.get("/api/ai/status")
        elapsed = time.time() - start

    assert res.status_code == 200
    assert elapsed < 7  # returned via the hard-timeout backstop, not the 8s call
    body = res.json()
    assert body["providers"][0]["provider"] == "anthropic"
    assert body["providers"][0]["usable"] is False
    assert "초" in body["providers"][0]["error"]
