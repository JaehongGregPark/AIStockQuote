"""Orchestration/state layer — replaces StockQuoteViewModel.kt.

Since this is now a stateless web backend rather than a stateful mobile
ViewModel, "UI state" becomes a short-lived server-side TTL cache instead:
each market/symbol result is cached briefly so switching tabs quickly or a
page reload doesn't re-trigger a full yfinance round trip every time.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.data.catalog import STOCK_CATALOG
from app.models.stock import MarketCategory, StockQuote, StockReference
from app.services import repository


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


_market_cache: Dict[MarketCategory, _CacheEntry] = {}
_detail_cache: Dict[str, _CacheEntry] = {}
_lock = asyncio.Lock()


def _resolve_reference(symbol: str, market: Optional[MarketCategory]) -> StockReference:
    candidate_markets = [market] if market is not None else list(STOCK_CATALOG.keys())
    for candidate_market in candidate_markets:
        for reference in STOCK_CATALOG.get(candidate_market, []):
            if reference.symbol == symbol:
                return reference
    return StockReference(symbol=symbol, display_name=symbol)


async def get_market_quotes(
    market: MarketCategory, force_refresh: bool = False
) -> Tuple[List[StockQuote], List[str]]:
    now = time.time()

    async with _lock:
        cached = _market_cache.get(market)
        if not force_refresh and cached is not None and cached.expires_at > now:
            return cached.value

    symbols = STOCK_CATALOG.get(market, [])
    quotes, failed = await repository.fetch_quotes(symbols)

    async with _lock:
        _market_cache[market] = _CacheEntry(
            value=(quotes, failed),
            expires_at=now + config.MARKET_CACHE_TTL_SECONDS,
        )
    return quotes, failed


async def get_quote_detail(
    symbol: str,
    market: Optional[MarketCategory] = None,
    force_refresh: bool = False,
) -> StockQuote:
    now = time.time()

    async with _lock:
        cached = _detail_cache.get(symbol)
        if not force_refresh and cached is not None and cached.expires_at > now:
            return cached.value

    reference = _resolve_reference(symbol, market)
    quote = await repository.fetch_quote_detail(reference)

    async with _lock:
        _detail_cache[symbol] = _CacheEntry(
            value=quote,
            expires_at=now + config.DETAIL_CACHE_TTL_SECONDS,
        )
    return quote


def clear_caches() -> None:
    """Mainly useful for tests."""
    _market_cache.clear()
    _detail_cache.clear()
