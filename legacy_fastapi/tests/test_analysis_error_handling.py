from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models.stock import StockQuote
from app.services import ai_analysis, quote_service

client = TestClient(app)


def test_get_quote_analysis_provider_error_is_graceful(monkeypatch):
    async def fake_get_quote_detail(symbol, market=None, force_refresh=False):
        return StockQuote(symbol=symbol, price=42.0, previous_close=40.0)

    async def fake_analyze_quote_raises(quote):
        raise RuntimeError("credit balance too low")

    monkeypatch.setattr(ai_analysis, "is_available", lambda: True)
    monkeypatch.setattr(quote_service, "get_quote_detail", fake_get_quote_detail)
    monkeypatch.setattr(ai_analysis, "analyze_quote", fake_analyze_quote_raises)
    monkeypatch.setattr(ai_analysis, "get_provider", lambda: "anthropic")
    monkeypatch.setattr(
        ai_analysis, "list_models", lambda provider=None: ["claude-haiku-4-5", "claude-opus-4-8"]
    )

    res = client.get("/api/quotes/AAPL/analysis")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is True
    assert body["analysis"] is None
    assert body["provider"] == "anthropic"
    assert "credit balance too low" in body["error"]
    assert body["available_models"] == ["claude-haiku-4-5", "claude-opus-4-8"]


def test_get_ai_status_reports_per_provider(monkeypatch):
    def fake_check(p):
        return {
            "provider": p,
            "configured": True,
            "model": f"model-{p}",
            "usable": p == "openai",
            "error": None if p == "openai" else "credit balance too low",
            "available_models": [] if p == "openai" else ["claude-haiku-4-5"],
        }

    monkeypatch.setattr(ai_analysis, "_PROVIDER_ORDER", ["anthropic", "openai"])
    monkeypatch.setattr(ai_analysis, "_provider_key", lambda p: "fake-key")
    monkeypatch.setattr(ai_analysis, "check_provider", fake_check)
    monkeypatch.setattr(ai_analysis, "get_provider", lambda: "openai")
    monkeypatch.setattr(config, "AI_PROVIDER", None)

    res = client.get("/api/ai/status")
    assert res.status_code == 200
    body = res.json()
    assert body["active_provider"] == "openai"
    assert body["ai_provider_override"] is None

    by_provider = {p["provider"]: p for p in body["providers"]}
    assert by_provider["anthropic"]["is_active"] is False
    assert by_provider["anthropic"]["usable"] is False
    assert by_provider["openai"]["is_active"] is True
    assert by_provider["openai"]["usable"] is True
