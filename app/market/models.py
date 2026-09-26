from enum import Enum
from dataclasses import dataclass
from typing import Optional

class CandleDataState(str, Enum):
    CONFIRMED_DATA = "CONFIRMED_DATA"
    STALE_DATA = "STALE_DATA"
    UNAVAILABLE_DATA = "UNAVAILABLE_DATA"

@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True

    def is_stale(self, max_age_seconds: int = 600) -> bool:
        # Pwedeng magdagdag ng custom stale logic kung kinakailangan
        return False
