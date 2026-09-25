from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from app.market.models import Candle, Quote, ProviderStatus

class MarketDataProvider(ABC):
    def __init__(self, name: str):
        self.name = name
        self.status = ProviderStatus.UNAVAILABLE
        self.last_success: Optional[str] = None
        self.last_failure: Optional[str] = None
        self.error_count: int = 0
        self.rate_limit_events: int = 0

    @abstractmethod
    async def connect(self) -> bool:
        pass

    @abstractmethod
    async def health_check(self) -> ProviderStatus:
        pass

    @abstractmethod
    async def get_quote(self, symbol: str) -> Optional[Quote]:
        pass

    @abstractmethod
    async def get_candles(self, symbol: str, timeframe: str, limit: int = 50) -> List[Candle]:
        pass
