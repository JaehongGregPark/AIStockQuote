"""New AI analysis feature (this had no Kotlin equivalent).

Generates a short natural-language summary of a stock's recent move using
the Anthropic API. The feature is fully optional: if ANTHROPIC_API_KEY is
not configured, `is_available()` returns False and callers should treat
the analysis as simply absent rather than an error.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from app import config
from app.models.stock import ChartPoint, StockQuote

_client = None
_client_init_attempted = False


def _get_client():
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True

    if not config.ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def is_available() -> bool:
    return _get_client() is not None


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


async def analyze_quote(quote: StockQuote) -> Optional[str]:
    client = _get_client()
    if client is None:
        return None

    prompt = _build_prompt(quote)
    loop = asyncio.get_event_loop()

    def _call() -> str:
        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in message.content if hasattr(block, "text")
        ).strip()

    return await loop.run_in_executor(None, _call)
