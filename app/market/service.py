# app/market/service.py
import logging
import math
import time
from typing import Dict, List, Optional

from app.market.models import Candle
from app.market.binance_provider import BinanceProvider
from app.market.twelvedata_provider import TwelveDataProvider

logger = logging.getLogger("trading_bot")

TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}
MAX_CANDLE_AGE_MULTIPLIER = 3


class MarketDataService:
    def __init__(self, binance_provider: Optional[BinanceProvider] = None,
                 twelvedata_provider: Optional[TwelveDataProvider] = None):
        self.binance = binance_provider or BinanceProvider()
        self.twelvedata = twelvedata_provider or TwelveDataProvider()
        self._cache: Dict[str, Dict[str, List[Candle]]] = {}
        self._last_update: Dict[str, Dict[str, float]] = {}
        self._last_error: Dict[str, str] = {}
        self.crypto_symbols = {"BTCUSD", "ETHUSD", "SOLUSD"}
        self.fx_metal_symbols = {
            "XAUUSD", "EURUSD", "GBPUSD", "USDJPY",
            "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
        }

    def normalize_symbol(self, raw_symbol: str) -> str:
        s = raw_symbol.upper().replace("=X", "").replace("-USD", "USD")
        if s in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
            s = s.replace("USDT", "USD")
        return s

    def _get_provider_for_symbol(self, raw_symbol: str):
        symbol = self.normalize_symbol(raw_symbol)
        if symbol in self.crypto_symbols:
            return self.binance, symbol
        if symbol in self.fx_metal_symbols:
            return self.twelvedata, symbol
        raise ValueError(f"UNSUPPORTED_SYMBOL | No provider mapped for symbol: {raw_symbol}")

    @staticmethod
    def _interval_seconds(timeframe: str) -> int:
        key = timeframe.upper()
        if key not in TIMEFRAME_SECONDS:
            raise ValueError(f"UNSUPPORTED_TIMEFRAME | {timeframe}")
        return TIMEFRAME_SECONDS[key]

    @classmethod
    def _validate_candles(cls, candles: List[Candle], timeframe: str,
                          now: Optional[float] = None) -> List[Candle]:
        """Return valid, closed, fresh candles sorted oldest-to-newest and deduplicated."""
        now = time.time() if now is None else now
        interval = cls._interval_seconds(timeframe)
        by_timestamp = {}
        for candle in candles or []:
            try:
                ts = int(candle.timestamp)
                o, h, low, close, volume = (
                    float(candle.open), float(candle.high), float(candle.low),
                    float(candle.close), float(candle.volume)
                )
                if not all(math.isfinite(v) for v in (o, h, low, close, volume)):
                    continue
                if min(o, h, low, close) <= 0 or volume < 0:
                    continue
                if h < max(o, low, close) or low > min(o, close):
                    continue
                # Provider timestamp is candle OPEN time; ignore unfinished/future bars.
                if ts + interval > now or ts > now:
                    continue
                candle.is_closed = True
                by_timestamp[ts] = candle
            except (TypeError, ValueError, OverflowError, AttributeError):
                continue
        ordered = [by_timestamp[k] for k in sorted(by_timestamp)]
        if not ordered:
            return []
        latest_close_time = int(ordered[-1].timestamp) + interval
        if now - latest_close_time > interval * MAX_CANDLE_AGE_MULTIPLIER:
            return []
        return ordered

    async def get_candles(self, symbol: str, timeframe: str = "M5",
                          limit: int = 50) -> List[Candle]:
        clean = self.normalize_symbol(symbol)
        tf = timeframe.upper()
        self._interval_seconds(tf)
        cached = self._cache.get(clean, {}).get(tf, [])
        if cached:
            validated = self._validate_candles(cached, tf)
            if validated:
                return validated[-limit:]
        ok = await self.update_symbol_data(clean, tf, limit=limit)
        return self._cache.get(clean, {}).get(tf, [])[-limit:] if ok else []

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5",
                                 limit: int = 50) -> bool:
        clean = self.normalize_symbol(symbol)
        tf = timeframe.upper()
        try:
            self._interval_seconds(tf)
            provider, provider_symbol = self._get_provider_for_symbol(clean)
            raw = await provider.get_candles(provider_symbol, tf, limit=limit)
            candles = self._validate_candles(raw, tf)
            if not candles:
                self._last_error[clean] = "NO_VALID_FRESH_CLOSED_CANDLES"
                logger.warning("MARKET_DATA_REJECTED | symbol=%s | timeframe=%s | reason=%s",
                               clean, tf, self._last_error[clean])
                return False
            self._cache.setdefault(clean, {})[tf] = candles[-limit:]
            self._last_update.setdefault(clean, {})[tf] = time.time()
            self._last_error.pop(clean, None)
            return True
        except Exception as exc:
            self._last_error[clean] = str(exc)
            logger.error("MARKET_DATA_UPDATE_ERROR | Symbol: %s | Error: %s", clean, exc)
            return False

    async def get_quote(self, symbol: str):
        """Use the latest validated M5 close; never synthesize or proxy a quote."""
        candles = await self.get_candles(symbol, "M5", limit=3)
        if not candles:
            return None
        latest = candles[-1]
        return {
            "symbol": self.normalize_symbol(symbol),
            "price": latest.close,
            "timestamp": int(latest.timestamp) + TIMEFRAME_SECONDS["M5"],
            "source": latest.source or latest.provider or "UNKNOWN",
            "is_closed_candle_price": True,
        }

    def get_health(self):
        health = {}
        for symbol, frames in self._cache.items():
            health[symbol] = {}
            for timeframe, candles in frames.items():
                valid = self._validate_candles(candles, timeframe)
                health[symbol][timeframe] = {
                    "status": "HEALTHY" if valid else "STALE_OR_UNAVAILABLE",
                    "provider": (valid[-1].provider or valid[-1].source) if valid else None,
                    "provider_symbol": valid[-1].provider_symbol if valid else None,
                    "closed_candle_count": len(valid),
                    "last_closed_candle_timestamp": (
                        int(valid[-1].timestamp) + TIMEFRAME_SECONDS[timeframe]
                    ) if valid else None,
                    "last_update_epoch": self._last_update.get(symbol, {}).get(timeframe),
                    "error": self._last_error.get(symbol),
                }
        return health


market_service = MarketDataService()
