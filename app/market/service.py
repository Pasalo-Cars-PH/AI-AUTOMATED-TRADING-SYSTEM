import datetime
from typing import Dict, List, Optional, Any
from app.market.models import Candle, Quote, DataQuality, ProviderStatus
from app.market.binance_provider import BinanceProvider
from app.market.twelvedata_provider import TwelveDataProvider

FRESHNESS_THRESHOLDS = {
    "M1": 90, "M5": 420, "M15": 1200,
    "M30": 2400, "H1": 5400, "H4": 18000, "D1": 93600
}

class MarketDataService:
    def __init__(self):
        self.binance = BinanceProvider()
        self.twelvedata = TwelveDataProvider()
        self.quotes_cache: Dict[str, Quote] = {}
        self.candles_cache: Dict[str, Dict[str, List[Candle]]] = {}
        self.data_gaps: List[Dict[str, Any]] = []

    async def initialize(self):
        await self.binance.connect()
        await self.twelvedata.connect()

    def get_provider_for_symbol(self, symbol: str):
        if symbol in ["BTCUSD", "ETHUSD", "SOLUSD"]:
            return self.binance
        return self.twelvedata

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5"):
        provider = self.get_provider_for_symbol(symbol)
        quote = await provider.get_quote(symbol)
        if quote:
            self.quotes_cache[symbol] = quote

        candles = await provider.get_candles(symbol, timeframe, limit=50)
        if candles:
            if symbol not in self.candles_cache:
                self.candles_cache[symbol] = {}
            
            # Deduplication & Storage
            existing = {c.timestamp: c for c in self.candles_cache[symbol].get(timeframe, [])}
            for c in candles:
                existing[c.timestamp] = c
            
            sorted_candles = sorted(existing.values(), key=lambda x: x.timestamp)
            self.candles_cache[symbol][timeframe] = sorted_candles

    def is_data_fresh(self, symbol: str, timeframe: str) -> bool:
        if symbol not in self.candles_cache or timeframe not in self.candles_cache[symbol]:
            return False
        candles = self.candles_cache[symbol][timeframe]
        if not candles:
            return False

        latest = candles[-1]
        try:
            ts_str = latest.timestamp.replace("Z", "")
            candle_time = datetime.datetime.fromisoformat(ts_str)
            now = datetime.datetime.utcnow()
            diff_sec = (now - candle_time).total_seconds()
            threshold = FRESHNESS_THRESHOLDS.get(timeframe, 600)
            return diff_sec <= threshold
        except Exception:
            return False

    def is_candle_closed(self, symbol: str, timeframe: str) -> bool:
        if symbol in self.candles_cache and timeframe in self.candles_cache[symbol]:
            candles = self.candles_cache[symbol][timeframe]
            if candles:
                return candles[-1].is_closed
        return False

    def get_quote(self, symbol: str) -> Optional[Quote]:
        return self.quotes_cache.get(symbol)

    def get_candles(self, symbol: str, timeframe: str) -> List[Candle]:
        return self.candles_cache.get(symbol, {}).get(timeframe, [])

    def get_status() -> Dict[str, Any]:
        stale_symbols = []
        for sym in ["BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD", "EURUSD", "GBPUSD"]:
            if not self.is_data_fresh(sym, "M5"):
                stale_symbols.append(sym)

        return {
            "status": "HEALTHY" if not stale_symbols else "DEGRADED",
            "providers": {
                "BINANCE": self.binance.status.value,
                "TWELVEDATA": self.twelvedata.status.value
            },
            "stale_symbols": stale_symbols,
            "data_gaps": self.data_gaps
        }

market_service = MarketDataService()
