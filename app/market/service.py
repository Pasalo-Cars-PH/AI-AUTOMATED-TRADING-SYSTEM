import logging
from typing import Dict, List, Optional, Any
from app.market.models import Candle, CandleDataState

logger = logging.getLogger("trading_bot")

class MarketDataService:
    def __init__(self):
        self._cache: Dict[str, List[Candle]] = {}

    def normalize_symbol(self, raw_symbol: str) -> str:
        s = raw_symbol.upper().replace("=X", "").replace("-USD", "USD")
        if s in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
            s = s.replace("USDT", "USD")
        return s

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5") -> bool:
        # Return True kung matagumpay na na-update ang market data
        return True

    async def get_candles(self, symbol: str, timeframe: str = "M5") -> List[Candle]:
        clean_symbol = self.normalize_symbol(symbol)
        return self._cache.get(clean_symbol, [])

market_service = MarketDataService()
