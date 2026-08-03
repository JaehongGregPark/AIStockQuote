from fastapi.testclient import TestClient

from app.main import app
from app.models.stock import StockQuote
from app.services import ai_analysis, quote_service

client = TestClient(app)


def test_list_markets():
    res = client.get("/api/markets")
    assert res.status_code == 200
    ids = {m["id"] for m in res.json()}
    assert ids == {"KOSPI", "KOSDAQ", "NASDAQ", "DOW"}


def test_get_market_quotes(monkeypatch):
    async def fake_get_market_quotes(market, force_refresh=False):
        return (
            [StockQuote(symbol="AAPL", price=100.0, previous_close=95.0)],
            ["BADSYM"],
        )

    monkeypatch.setattr(quote_service, "get_market_quotes", fake_get_market_quotes)

    res = client.get("/api/markets/NASDAQ/quotes")
    assert res.status_code == 200
    body = res.json()
    assert body["quotes"][0]["symbol"] == "AAPL"
    assert body["failed_symbols"] == ["BADSYM"]


def test_get_market_quotes_unknown_market():
    res = client.get("/api/markets/FAKE/quotes")
    assert res.status_code == 404


def test_get_quote_detail(monkeypatch):
    async def fake_get_quote_detail(symbol, market=None, force_refresh=False):
        return StockQuote(symbol=symbol, price=42.0, previous_close=40.0)

    monkeypatch.setattr(quote_service, "get_quote_detail", fake_get_quote_detail)

    res = client.get("/api/quotes/AAPL")
    assert res.status_code == 200
    assert res.json()["symbol"] == "AAPL"


def test_get_quote_analysis_disabled(monkeypatch):
    monkeypatch.setattr(ai_analysis, "is_available", lambda: False)

    res = client.get("/api/quotes/AAPL/analysis")
    assert res.status_code == 200
    assert res.json() == {"available": False, "analysis": None}


def test_get_quote_analysis_enabled(monkeypatch):
    async def fake_get_quote_detail(symbol, market=None, force_refresh=False):
        return StockQuote(symbol=symbol, price=42.0, previous_close=40.0)

    async def fake_analyze_quote(quote):
        return "테스트 분석 결과"

    monkeypatch.setattr(ai_analysis, "is_available", lambda: True)
    monkeypatch.setattr(quote_service, "get_quote_detail", fake_get_quote_detail)
    monkeypatch.setattr(ai_analysis, "analyze_quote", fake_analyze_quote)
    monkeypatch.setattr(ai_analysis, "get_provider", lambda: "anthropic")

    res = client.get("/api/quotes/AAPL/analysis")
    assert res.status_code == 200
    assert res.json() == {
        "available": True,
        "analysis": "테스트 분석 결과",
        "provider": "anthropic",
    }
