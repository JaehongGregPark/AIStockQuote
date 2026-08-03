"""REST endpoints — replaces the Compose UI's ViewModel-driven navigation
with a plain HTTP API that the static frontend (or any other client)
consumes.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import config
from app.models.stock import MARKET_INFO, MarketCategory
from app.services import ai_analysis, quote_service

_API_KEY_ATTR = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
_MODEL_ATTR = {
    "anthropic": "ANTHROPIC_MODEL",
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
}


class ProviderConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None


class ActiveProviderUpdate(BaseModel):
    # None/"" means "auto" — pick by priority (anthropic -> openai -> gemini).
    provider: Optional[str] = None


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

    provider = ai_analysis.get_provider()
    try:
        text = await ai_analysis.analyze_quote(quote)
    except Exception as exc:  # noqa: BLE001 - provider API errors (billing, rate limit, etc.)
        loop = asyncio.get_event_loop()
        available_models = await loop.run_in_executor(None, ai_analysis.list_models, provider)
        return {
            "available": True,
            "analysis": None,
            "provider": provider,
            "error": str(exc),
            "available_models": available_models,
        }
    return {"available": True, "analysis": text, "provider": provider}


async def _check_provider_bounded(provider: str) -> dict:
    """Run `check_provider` in a worker thread with a hard timeout, so a
    provider whose network call hangs (unreachable host, SDK ignoring its
    own timeout, etc.) can never block the response forever.
    """
    loop = asyncio.get_event_loop()
    # A little slack on top of the per-request timeout used inside
    # ai_analysis, since that timeout is enforced by the SDK/HTTP layer and
    # this one is our own backstop.
    hard_timeout = config.AI_REQUEST_TIMEOUT_SECONDS + 5
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, ai_analysis.check_provider, provider),
            timeout=hard_timeout,
        )
    except asyncio.TimeoutError:
        return {
            "provider": provider,
            "configured": bool(ai_analysis._provider_key(provider)),
            "model": ai_analysis._configured_model(provider),
            "usable": False,
            "error": f"응답이 {hard_timeout}초 내에 오지 않았습니다 (네트워크 연결을 확인하세요).",
            "available_models": [],
        }


@router.get("/ai/status")
async def get_ai_status():
    """Report every supported AI provider (anthropic/openai/gemini).

    Providers without an API key are reported instantly as unconfigured
    (check_provider short-circuits before making any network call).
    Configured providers get a real minimal API call, run concurrently and
    each bounded by a hard timeout, so one unreachable/misconfigured
    provider can't stall the whole response. If the configured model isn't
    usable with the current key, the models that ARE usable are included.

    Also reports which provider AI analysis actually uses right now
    (`active_provider`) and whether that's from an explicit override
    (`ai_provider_override`) or the default priority order.
    """
    results = await asyncio.gather(
        *(_check_provider_bounded(p) for p in ai_analysis._PROVIDER_ORDER)
    )
    active_provider = ai_analysis.get_provider()
    for r in results:
        r["is_active"] = r["provider"] == active_provider

    return {
        "providers": list(results),
        "active_provider": active_provider,
        "ai_provider_override": config.AI_PROVIDER,
    }


@router.post("/ai/config/{provider}")
async def update_ai_provider_config(provider: str, body: ProviderConfigUpdate):
    """Set the API key and/or model for one provider.

    Updates the running server's in-memory config immediately AND writes
    the same value into the .env file, so it survives a server restart.
    Blank values are ignored (they don't clear an existing key/model).
    """
    if provider not in ai_analysis._PROVIDER_ORDER:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    persisted = False

    if body.api_key is not None and body.api_key.strip():
        key_attr = _API_KEY_ATTR[provider]
        value = body.api_key.strip()
        setattr(config, key_attr, value)
        config.persist_env_value(key_attr, value)
        persisted = True

    if body.model is not None and body.model.strip():
        model_attr = _MODEL_ATTR[provider]
        value = body.model.strip()
        setattr(config, model_attr, value)
        config.persist_env_value(model_attr, value)
        persisted = True

    ai_analysis.reset_client_cache()

    result = await _check_provider_bounded(provider)
    result["persisted_to_env"] = persisted
    return result


@router.post("/ai/active-provider")
async def set_active_provider(body: ActiveProviderUpdate):
    """Choose which provider AI analysis should use.

    Passing a provider name pins it (AI_PROVIDER override); passing null/""
    clears the override and falls back to the default priority order
    (anthropic -> openai -> gemini, first one with a configured key). The
    choice is written to .env immediately, so it survives a restart.
    """
    provider = (body.provider or "").strip().lower() or None
    if provider is not None and provider not in ai_analysis._PROVIDER_ORDER:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    config.AI_PROVIDER = provider
    config.persist_env_value("AI_PROVIDER", provider or "")
    ai_analysis.reset_client_cache()

    return await get_ai_status()
