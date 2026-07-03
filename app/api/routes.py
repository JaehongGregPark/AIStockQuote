"""REST endpoints — replaces the Compose UI's ViewModel-driven navigation
with a plain HTTP API that the static frontend (or any other client)
consumes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.stock import MARKET_INFO, MarketCategory
from app.services import ai_analysis, quote_service

router = APIRouter(prefix="/api")


def _parse_market(market_id: str) -> MarketCategory:
    try:
        return MarketCategory[market_id.upper()]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown market: {market_id}")


@router.get("/markets")
async def list_markets():
    return [
        {
            "id": market.value,
            "title": MARKET_INFO[market]["title"],
            "description": MARKET_INFO[market]["description"],
        }
        for market in MarketCategory
    ]


@router.get("/markets/{market_id}/quotes")
async def get_market_quotes(market_id: str, refresh: bool = Query(False)):
    market = _parse_market(market_id)
    quotes, failed = await quote_service.get_market_quotes(market, force_refresh=refresh)
    return {
        "market": market.value,
        "quotes": [quote.model_dump() for quote in quotes],
        "failed_symbols": failed,
    }


@router.get("/quotes/{symbol}")
async def get_quote_detail(
    symbol: str,
    market: Optional[str] = None,
    refresh: bool = Query(False),
):
    market_enum = _parse_market(market) if market else None
    try:
        quote = await quote_service.get_quote_detail(
            symbol.strip().upper(), market=market_enum, force_refresh=refresh
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as 502
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return quote.model_dump()


@router.get("/quotes/{symbol}/analysis")
async def get_quote_analysis(symbol: str, market: Optional[str] = None):
    if not ai_analysis.is_available():
        return {"available": False, "analysis": None}

    market_enum = _parse_market(market) if market else None
    try:
        quote = await quote_service.get_quote_detail(
            symbol.strip().upper(), market=market_enum
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    text = await ai_analysis.analyze_quote(quote)
    return {"available": True, "analysis": text}
