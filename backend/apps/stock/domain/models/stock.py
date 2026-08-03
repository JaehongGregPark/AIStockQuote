"""Core domain models, ported from the original Kotlin data classes
(StockModels.kt) to Pydantic models.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, computed_field


class MarketCategory(str, Enum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    NASDAQ = "NASDAQ"
    DOW = "DOW"


MARKET_INFO: Dict[MarketCategory, Dict[str, str]] = {
    MarketCategory.KOSPI: {
        "title": "KOSPI 주요 종목",
        "description": "KOSPI 지수 전체가 아닌 시가총액·인지도를 참고해 자체 선정한 주요 종목 큐레이션입니다.",
    },
    MarketCategory.KOSDAQ: {
        "title": "KOSDAQ 주요 종목",
        "description": "KOSDAQ 지수 전체가 아닌 시가총액·거래 관심도를 참고한 주요 종목 큐레이션입니다.",
    },
    MarketCategory.NASDAQ: {
        "title": "NASDAQ 주요 종목",
        "description": "NASDAQ 구성종목 전체가 아닌 대형 기술주 중심 자체 큐레이션입니다.",
    },
    MarketCategory.DOW: {
        "title": "Dow 주요 구성종목",
        "description": "Dow Jones 구성종목 중 대표 대형주를 선별한 주요 종목 목록입니다.",
    },
}


class StockReference(BaseModel):
    symbol: str
    display_name: str


class ChartPoint(BaseModel):
    timestamp: int
    close: float
    volume: Optional[int] = None


class StockQuote(BaseModel):
    symbol: str
    short_name: Optional[str] = None
    currency: Optional[str] = None
    exchange_name: Optional[str] = None
    price: float
    previous_close: Optional[float] = None
    market_time: Optional[int] = None
    market_cap: Optional[int] = None
    open_price: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    chart_points: List[ChartPoint] = []
    fifty_two_week_low: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    trailing_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    regular_market_price: Optional[float] = None
    pre_market_price: Optional[float] = None
    post_market_price: Optional[float] = None
    financial_trends: List[dict] = []

    @computed_field  # type: ignore[misc]
    @property
    def change_amount(self) -> Optional[float]:
        if self.previous_close is None:
            return None
        return self.price - self.previous_close

    @computed_field  # type: ignore[misc]
    @property
    def change_percent(self) -> Optional[float]:
        if not self.previous_close:
            return None
        return ((self.price - self.previous_close) / self.previous_close) * 100.0
