from abc import ABC, abstractmethod
from typing import List
from app.data.normalizer import MarketCandle

class BaseDataProvider(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> List[MarketCandle]:
        pass
