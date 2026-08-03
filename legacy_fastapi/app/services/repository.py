"""Data access layer — fetches quotes/history via yfinance.

This replaces StockQuoteRepository.kt. The original Kotlin version fetched
each symbol sequentially over HTTP, which meant a 20-symbol market view
could take a long time if any single request was slow. Here, all symbol
fetches for a market are dispatched concurrently across a thread pool
(yfinance's underlying calls are blocking), which is the main performance
fix identified during the original code review.
"""
from __future__ import annotations

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

import yfinance as yf

from app import config
from app.models.stock import ChartPoint, StockQuote, StockReference

_executor = ThreadPoolExecutor(max_workers=config.FETCH_MAX_WORKERS)


class QuoteFetchError(Exception):
    """Raised when a single symbol's quote/history could not be retrieved."""


def _safe_float(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _fetch_single_quote_sync(
    reference: StockReference,
    period: str,
    include_chart: bool,
) -> StockQuote:
    """Blocking call — must be run in a worker thread."""
    ticker = yf.Ticker(reference.symbol)
    hist = ticker.history(period=period, interval="1d")

    if hist.empty:
        raise QuoteFetchError(f"No data was found for {reference.symbol}.")

    closes = hist["Close"].dropna()
    if closes.empty:
        raise QuoteFetchError(f"Current price is unavailable for {reference.symbol}.")

    price = _safe_float(closes.iloc[-1])
    if price is None:
        raise QuoteFetchError(f"Current price is unavailable for {reference.symbol}.")

    previous_close = _safe_float(closes.iloc[-2]) if len(closes) >= 2 else None

    currency: Optional[str] = None
    exchange_name: Optional[str] = None
    short_name: Optional[str] = reference.display_name
    try:
        fast_info = ticker.fast_info
        currency = fast_info.get("currency")
        exchange_name = fast_info.get("exchange")
    except Exception:
        # fast_info can fail independently of history(); quote is still usable.
        pass

    last_row = hist.iloc[-1]
    last_timestamp = hist.index[-1]
    market_time = int(last_timestamp.timestamp())

    chart_points: List[ChartPoint] = []
    if include_chart:
        for ts, close_value in closes.items():
            close_f = _safe_float(close_value)
            if close_f is None:
                continue
            chart_points.append(ChartPoint(timestamp=int(ts.timestamp()), close=close_f))

    return StockQuote(
        symbol=reference.symbol,
        short_name=short_name,
        currency=currency,
        exchange_name=exchange_name,
        price=price,
        previous_close=previous_close,
        market_time=market_time,
        market_cap=None,
        open_price=_safe_float(last_row.get("Open")),
        day_high=_safe_float(last_row.get("High")),
        day_low=_safe_float(last_row.get("Low")),
        chart_points=chart_points,
    )


async def fetch_quotes(
    symbols: List[StockReference],
) -> Tuple[List[StockQuote], List[str]]:
    """Fetch a short-range quote for every symbol concurrently.

    Returns (successful_quotes, failed_symbols) — a single bad symbol no
    longer aborts the whole market view, but callers are told which symbols
    were dropped instead of the failure being silently swallowed.
    """
    if not symbols:
        return [], []

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(_executor, _fetch_single_quote_sync, ref, "5d", False)
        for ref in symbols
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    quotes: List[StockQuote] = []
    failed: List[str] = []
    for reference, result in zip(symbols, results):
        if isinstance(result, Exception):
            failed.append(reference.symbol)
        else:
            quotes.append(result)
    return quotes, failed


async def fetch_quote_detail(reference: StockReference) -> StockQuote:
    """Fetch a 1-month history (used for the detail view + price chart)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, _fetch_single_quote_sync, reference, "1mo", True
    )
