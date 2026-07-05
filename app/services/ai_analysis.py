"""AI analysis feature (this had no Kotlin equivalent).

Generates a short natural-language summary of a stock's recent move using
one of the supported AI providers: Anthropic (Claude), OpenAI, or Google
Gemini. The feature is fully optional: if no provider API key is
configured, `is_available()` returns False and callers should treat the
analysis as simply absent rather than an error.

Provider selection:
- If AI_PROVIDER is set ("anthropic" | "openai" | "gemini"), that provider
  is used, provided its API key is also configured.
- Otherwise, the first configured key wins, checked in this order:
  anthropic -> openai -> gemini.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from app import config
from app.models.stock import ChartPoint, StockQuote

_PROVIDER_ORDER = ["anthropic", "openai", "gemini"]

_client = None
_provider: Optional[str] = None
_client_init_attempted = False


def _provider_key(provider: str) -> Optional[str]:
    return {
        "anthropic": config.ANTHROPIC_API_KEY,
        "openai": config.OPENAI_API_KEY,
        "gemini": config.GEMINI_API_KEY,
    }.get(provider)


def _resolve_provider() -> Optional[str]:
    if config.AI_PROVIDER:
        if config.AI_PROVIDER in _PROVIDER_ORDER and _provider_key(config.AI_PROVIDER):
            return config.AI_PROVIDER
        return None  # explicitly requested provider has no key configured

    for provider in _PROVIDER_ORDER:
        if _provider_key(provider):
            return provider
    return None


def _anthropic_client(key: str):
    import anthropic

    # timeout + max_retries=0: a stuck/unreachable provider must fail fast
    # instead of hanging (SDK defaults can retry for minutes).
    return anthropic.Anthropic(
        api_key=key, timeout=config.AI_REQUEST_TIMEOUT_SECONDS, max_retries=0
    )


def _openai_client(key: str):
    import openai

    return openai.OpenAI(
        api_key=key, timeout=config.AI_REQUEST_TIMEOUT_SECONDS, max_retries=0
    )


def _gemini_request_options() -> dict:
    return {"timeout": config.AI_REQUEST_TIMEOUT_SECONDS}


def _build_client(provider: str):
    if provider == "anthropic":
        return _anthropic_client(config.ANTHROPIC_API_KEY)

    if provider == "openai":
        return _openai_client(config.OPENAI_API_KEY)

    if provider == "gemini":
        import google.generativeai as genai

        genai.configure(api_key=config.GEMINI_API_KEY)
        return genai.GenerativeModel(config.GEMINI_MODEL)

    raise ValueError(f"Unknown AI provider: {provider}")


def _get_client():
    global _client, _client_init_attempted, _provider
    if _client_init_attempted:
        return _client
    _client_init_attempted = True

    provider = _resolve_provider()
    if provider is None:
        return None

    try:
        _client = _build_client(provider)
    except ImportError:
        # Corresponding SDK package isn't installed; treat as unavailable.
        return None

    _provider = provider
    return _client


def is_available() -> bool:
    return _get_client() is not None


def get_provider() -> Optional[str]:
    """Name of the active provider, or None if AI analysis is unavailable."""
    _get_client()
    return _provider


def reset_client_cache() -> None:
    """Forget the cached client/provider so the next call re-resolves them.

    Needed after an API key or model is changed at runtime (e.g. via the
    API-key panel), since `_get_client()` otherwise only resolves once.
    """
    global _client, _provider, _client_init_attempted
    _client = None
    _provider = None
    _client_init_attempted = False


def _summarize_trend(points: List[ChartPoint]) -> str:
    if len(points) < 2:
        return "차트 데이터가 충분하지 않습니다."
    start = points[0].close
    end = points[-1].close
    if start == 0:
        return "차트 데이터가 충분하지 않습니다."
    change_pct = ((end - start) / start) * 100.0
    direction = "상승" if change_pct >= 0 else "하락"
    return f"기간 시작 {start:.2f} → 현재 {end:.2f} ({direction} {abs(change_pct):.2f}%)"


def _build_prompt(quote: StockQuote) -> str:
    trend = _summarize_trend(quote.chart_points)
    change_pct = quote.change_percent
    change_pct_text = f"{change_pct:.2f}%" if change_pct is not None else "알 수 없음"

    return (
        "다음 주식 데이터를 참고해서 오늘의 등락과 최근 한 달간의 추세를 "
        "한국어로 2~3문장, 쉬운 말로 짧게 설명해줘. 투자 조언이나 매수/매도 "
        "추천은 하지 말고, 사실 요약만 해줘.\n\n"
        f"종목명: {quote.short_name or quote.symbol} ({quote.symbol})\n"
        f"현재가: {quote.price} {quote.currency or ''}\n"
        f"전일 종가: {quote.previous_close}\n"
        f"등락률: {change_pct_text}\n"
        f"최근 1개월 추세: {trend}\n"
    )


def _call_anthropic(client, prompt: str) -> str:
    message = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in message.content if hasattr(block, "text")
    ).strip()


def _call_openai(client, prompt: str) -> str:
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return (response.choices[0].message.content or "").strip()


def _call_gemini(client, prompt: str) -> str:
    response = client.generate_content(prompt, request_options=_gemini_request_options())
    return (response.text or "").strip()


_CALLERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


async def analyze_quote(quote: StockQuote) -> Optional[str]:
    client = _get_client()
    if client is None:
        return None

    prompt = _build_prompt(quote)
    loop = asyncio.get_event_loop()
    caller = _CALLERS[_provider]

    return await loop.run_in_executor(None, lambda: caller(client, prompt))


_MODEL_GETTERS = {
    "anthropic": lambda: config.ANTHROPIC_MODEL,
    "openai": lambda: config.OPENAI_MODEL,
    "gemini": lambda: config.GEMINI_MODEL,
}


def _configured_model(provider: str) -> Optional[str]:
    getter = _MODEL_GETTERS.get(provider)
    return getter() if getter else None


def list_models(provider: Optional[str] = None) -> List[str]:
    """Return the model IDs actually usable with `provider`'s API key.

    Useful when the configured model turns out to be inaccessible (wrong
    name, no access, deprecated, region-locked, ...) so the caller can
    present working alternatives for the same key. Returns an empty list
    if the key is missing/invalid or the lookup itself fails.
    """
    provider = provider or _provider
    if provider is None:
        return []

    key = _provider_key(provider)
    if not key:
        return []

    try:
        if provider == "anthropic":
            client = _anthropic_client(key)
            return [m.id for m in client.models.list().data]

        if provider == "openai":
            client = _openai_client(key)
            return sorted(m.id for m in client.models.list().data)

        if provider == "gemini":
            import google.generativeai as genai

            genai.configure(api_key=key)
            return [
                m.name
                for m in genai.list_models(request_options=_gemini_request_options())
                if "generateContent" in getattr(m, "supported_generation_methods", [])
            ]
    except Exception:
        return []

    return []


def check_provider(provider: str) -> dict:
    """Make a minimal real API call to verify `provider`'s configured key
    and model actually work together. If the call fails, also fetches the
    list of models that ARE usable with the same key.
    """
    key = _provider_key(provider)
    model = _configured_model(provider)
    result = {
        "provider": provider,
        "configured": bool(key),
        "model": model,
        "usable": False,
        "error": None,
        "available_models": [],
    }

    if not key:
        result["error"] = "API 키가 설정되어 있지 않습니다."
        return result

    try:
        if provider == "anthropic":
            _anthropic_client(key).messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        elif provider == "openai":
            _openai_client(key).chat.completions.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        elif provider == "gemini":
            import google.generativeai as genai

            genai.configure(api_key=key)
            genai.GenerativeModel(model).generate_content(
                "ping",
                generation_config={"max_output_tokens": 1},
                request_options=_gemini_request_options(),
            )
        else:
            result["error"] = f"알 수 없는 provider: {provider}"
            return result
    except ImportError:
        result["error"] = f"{provider} SDK가 설치되어 있지 않습니다."
        return result
    except Exception as exc:  # noqa: BLE001 - any API error (auth/billing/model access/...)
        result["error"] = str(exc)
        result["available_models"] = list_models(provider)
        return result

    result["usable"] = True
    return result


def check_all_providers() -> List[dict]:
    """Run `check_provider` for every provider that has an API key configured."""
    return [check_provider(p) for p in _PROVIDER_ORDER if _provider_key(p)]
