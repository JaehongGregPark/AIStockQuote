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
        "title": "KOSPI",
        "description": "Top 20 large-cap names in Korea's main market",
    },
    MarketCategory.KOSDAQ: {
        "title": "KOSDAQ",
        "description": "Top 20 large-cap names in Korea's growth market",
    },
    MarketCategory.NASDAQ: {
        "title": "NASDAQ",
        "description": "Top 20 mega-cap Nasdaq stocks",
    },
    MarketCategory.DOW: {
        "title": "DOW",
        "description": "Large-cap Dow Jones components",
    },
}


class StockReference(BaseModel):
    symbol: str
    display_name: str


class ChartPoint(BaseModel):
    timestamp: int
    close: float


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
