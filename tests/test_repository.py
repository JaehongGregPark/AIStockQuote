import pandas as pd
import pytest

from app.models.stock import StockReference
from app.services import repository


class FakeTicker:
    def __init__(self, history_df, fast_info=None, raise_on_history=False):
        self._history_df = history_df
        self._fast_info = fast_info or {}
        self._raise_on_history = raise_on_history

    def history(self, period, interval):
        if self._raise_on_history:
            raise RuntimeError("network error")
        return self._history_df

    @property
    def fast_info(self):
        return self._fast_info


def _make_history(dates, closes, opens=None, highs=None, lows=None):
    data = {
        "Open": opens or closes,
        "High": highs or closes,
        "Low": lows or closes,
        "Close": closes,
    }
    return pd.DataFrame(data, index=pd.to_datetime(dates, utc=True))


def test_fetch_single_quote_sync_computes_previous_close(monkeypatch):
    dates = ["2026-06-01", "2026-06-02", "2026-06-03"]
    closes = [100.0, 105.0, 110.0]
    fake_ticker = FakeTicker(
        _make_history(dates, closes),
        fast_info={"currency": "USD", "exchange": "NMS"},
    )
    monkeypatch.setattr(repository.yf, "Ticker", lambda symbol: fake_ticker)

    reference = StockReference(symbol="AAPL", display_name="Apple")
    quote = repository._fetch_single_quote_sync(reference, period="5d", include_chart=False)

    assert quote.price == 110.0
    assert quote.previous_close == 105.0
    assert quote.currency == "USD"
    assert quote.exchange_name == "NMS"
    assert quote.chart_points == []
    # computed fields
    assert quote.change_amount == pytest.approx(5.0)
    assert quote.change_percent == pytest.approx((5.0 / 105.0) * 100.0)


def test_fetch_single_quote_sync_builds_chart_points(monkeypatch):
    dates = ["2026-06-01", "2026-06-02"]
    closes = [50.0, 55.0]
    fake_ticker = FakeTicker(_make_history(dates, closes))
    monkeypatch.setattr(repository.yf, "Ticker", lambda symbol: fake_ticker)

    reference = StockReference(symbol="TEST", display_name="Test Co")
    quote = repository._fetch_single_quote_sync(reference, period="1mo", include_chart=True)

    assert len(quote.chart_points) == 2
    assert quote.chart_points[-1].close == 55.0


def test_fetch_single_quote_sync_raises_on_empty_history(monkeypatch):
    empty_df = pd.DataFrame({"Open": [], "High": [], "Low": [], "Close": []})
    fake_ticker = FakeTicker(empty_df)
    monkeypatch.setattr(repository.yf, "Ticker", lambda symbol: fake_ticker)

    reference = StockReference(symbol="EMPTY", display_name="Empty")
    with pytest.raises(repository.QuoteFetchError):
        repository._fetch_single_quote_sync(reference, period="5d", include_chart=False)


async def test_fetch_quotes_partial_failure(monkeypatch):
    good_history = _make_history(["2026-06-01", "2026-06-02"], [10.0, 12.0])

    def fake_ticker_factory(symbol):
        if symbol == "BAD":
            return FakeTicker(good_history, raise_on_history=True)
        return FakeTicker(good_history)

    monkeypatch.setattr(repository.yf, "Ticker", fake_ticker_factory)

    symbols = [
        StockReference(symbol="GOOD", display_name="Good Co"),
        StockReference(symbol="BAD", display_name="Bad Co"),
    ]
    quotes, failed = await repository.fetch_quotes(symbols)

    assert [q.symbol for q in quotes] == ["GOOD"]
    assert failed == ["BAD"]
