import pytest

from app.models.stock import MarketCategory, StockQuote
from app.services import quote_service, repository


@pytest.fixture(autouse=True)
def _clear_cache():
    quote_service.clear_caches()
    yield
    quote_service.clear_caches()


async def test_get_market_quotes_uses_cache(monkeypatch):
    call_count = {"n": 0}

    async def fake_fetch_quotes(symbols):
        call_count["n"] += 1
        return ([], [])

    monkeypatch.setattr(repository, "fetch_quotes", fake_fetch_quotes)

    await quote_service.get_market_quotes(MarketCategory.NASDAQ)
    await quote_service.get_market_quotes(MarketCategory.NASDAQ)

    assert call_count["n"] == 1


async def test_get_market_quotes_force_refresh_bypasses_cache(monkeypatch):
    call_count = {"n": 0}

    async def fake_fetch_quotes(symbols):
        call_count["n"] += 1
        return ([], [])

    monkeypatch.setattr(repository, "fetch_quotes", fake_fetch_quotes)

    await quote_service.get_market_quotes(MarketCategory.NASDAQ)
    await quote_service.get_market_quotes(MarketCategory.NASDAQ, force_refresh=True)

    assert call_count["n"] == 2


async def test_get_quote_detail_resolves_reference_from_catalog(monkeypatch):
    captured = {}

    async def fake_fetch_quote_detail(reference):
        captured["reference"] = reference
        return StockQuote(symbol=reference.symbol, price=1.0)

    monkeypatch.setattr(repository, "fetch_quote_detail", fake_fetch_quote_detail)

    await quote_service.get_quote_detail("AAPL", market=MarketCategory.NASDAQ)

    assert captured["reference"].display_name == "Apple"


async def test_get_quote_detail_falls_back_to_bare_symbol(monkeypatch):
    captured = {}

    async def fake_fetch_quote_detail(reference):
        captured["reference"] = reference
        return StockQuote(symbol=reference.symbol, price=1.0)

    monkeypatch.setattr(repository, "fetch_quote_detail", fake_fetch_quote_detail)

    await quote_service.get_quote_detail("UNKNOWN123")

    assert captured["reference"].symbol == "UNKNOWN123"
    assert captured["reference"].display_name == "UNKNOWN123"
