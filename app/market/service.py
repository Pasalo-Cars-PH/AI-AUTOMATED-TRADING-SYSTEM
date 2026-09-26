import datetime
import logging
from typing import Dict, List, Optional, Any
from app.market.models import Candle, Quote, DataQuality, ProviderStatus
from app.market.binance_provider import BinanceProvider
from app.market.twelvedata_provider import TwelveDataProvider

logger = logging.getLogger("trading_bot")

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
        if symbol.upper() in ["BTCUSD", "ETHUSD", "SOLUSD", "BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            return self.binance
        return self.twelvedata

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5"):
        provider = self.get_provider_for_symbol(symbol)
        try:
            quote = await provider.get_quote(symbol)
            if quote:
                self.quotes_cache[symbol.upper()] = quote

            candles = await provider.get_candles(symbol, timeframe, limit=50)
            if candles:
                if symbol.upper() not in self.candles_cache:
                    self.candles_cache[symbol.upper()] = {}
                
                existing = {c.timestamp: c for c in self.candles_cache[symbol.upper()].get(timeframe.upper(), [])}
                for c in candles:
                    existing[c.timestamp] = c
                
                sorted_candles = sorted(existing.values(), key=lambda x: x.timestamp)
                self.candles_cache[symbol.upper()][timeframe.upper()] = sorted_candles
        except Exception as e:
            logger.error(f"Error updating symbol data for {symbol}: {e}")

    def is_data_fresh(self, symbol: str, timeframe: str) -> bool:
        sym = symbol.upper()
        tf = timeframe.upper()
        if sym not in self.candles_cache or tf not in self.candles_cache[sym]:
            return False
        candles = self.candles_cache[sym][tf]
        if not candles:
            return False

        latest = candles[-1]
        try:
            ts_str = latest.timestamp.replace("Z", "")
            candle_time = datetime.datetime.fromisoformat(ts_str)
            now = datetime.datetime.utcnow()
            diff_sec = (now - candle_time).total_seconds()
            threshold = FRESHNESS_THRESHOLDS.get(tf, 600)
            return diff_sec <= threshold
        except Exception:
            return False

    def is_candle_closed(self, symbol: str, timeframe: str) -> bool:
        sym = symbol.upper()
        tf = timeframe.upper()
        if sym in self.candles_cache and tf in self.candles_cache[sym]:
            candles = self.candles_cache[sym][tf]
            if candles:
                return candles[-1].is_closed
        return False

    async def get_quote_async(self, symbol: str) -> Optional[Quote]:
        sym = symbol.upper()
        if sym in self.quotes_cache:
            return self.quotes_cache[sym]
        provider = self.get_provider_for_symbol(sym)
        quote = await provider.get_quote(sym)
        if quote:
            self.quotes_cache[sym] = quote
        return quote

    async def get_candles_async(self, symbol: str, timeframe: str) -> List[Candle]:
        sym = symbol.upper()
        tf = timeframe.upper()
        if sym in self.candles_cache and tf in self.candles_cache[sym]:
            return self.candles_cache[sym][tf]
        provider = self.get_provider_for_symbol(sym)
        candles = await provider.get_candles(sym, tf, limit=50)
        if candles:
            if sym not in self.candles_cache:
                self.candles_cache[sym] = {}
            self.candles_cache[sym][tf] = candles
        return candles

    def get_status(self) -> Dict[str, Any]:
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
