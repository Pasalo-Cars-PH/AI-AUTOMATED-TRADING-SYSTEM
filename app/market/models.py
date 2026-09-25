import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class DataQuality(str, Enum):
    CONFIRMED_DATA = "CONFIRMED_DATA"
    STALE_DATA = "STALE_DATA"
    MISSING_DATA = "MISSING_DATA"
    UNAVAILABLE_DATA = "UNAVAILABLE_DATA"
    INVALID_DATA = "INVALID_DATA"

class ProviderStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    MISCONFIGURED = "MISCONFIGURED"

class Candle(BaseModel):
    symbol: str
    timestamp: str  # ISO Format UTC
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    provider_symbol: str
    is_closed: bool
    received_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    quality: DataQuality = DataQuality.CONFIRMED_DATA

class Quote(BaseModel):
    symbol: str
    timestamp: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: float
    spread: Optional[float] = None
    source: str
    provider_symbol: str
    received_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    quality: DataQuality = DataQuality.CONFIRMED_DATA
