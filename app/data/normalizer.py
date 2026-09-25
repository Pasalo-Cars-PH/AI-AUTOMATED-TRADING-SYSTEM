from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel

class DataQualityState(str, Enum):
    CONFIRMED_DATA = "CONFIRMED_DATA"
    CALCULATED_DATA = "CALCULATED_DATA"
    AI_INTERPRETATION = "AI_INTERPRETATION"
    MISSING_DATA = "MISSING_DATA"
    UNAVAILABLE_DATA = "UNAVAILABLE_DATA"

class MarketCandle(BaseModel):
    symbol: str
    timestamp: datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    quality_state: DataQualityState = DataQualityState.CONFIRMED_DATA
