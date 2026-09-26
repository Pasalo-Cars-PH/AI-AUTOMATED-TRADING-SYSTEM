import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from app.market.providers.binance import BinanceProvider
from app.market.providers.yahoo import YahooFXProvider

logger = logging.getLogger("trading_bot")

SYMBOL_MAP = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "SOLUSD": "SOLUSDT",
    "XAUUSD=X": "GC=F",
    "EURUSD=X": "EURUSD=X"
}

TIMEFRAME_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "D1": "1d"
}

def normalize_symbol(symbol: str) -> str:
    return symbol.upper().strip()

def normalize_timeframe(tf: str) -> str:
    return tf.upper().strip()

class MarketDataService:
    def __init__(self):
        self.binance_provider = BinanceProvider()
        self.yahoo_provider = YahooFXProvider()
        self._store: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        self._health_status: Dict[str, Dict[str, Any]] = {}

    def _get_provider_for_symbol(self, symbol: str):
        norm_sym = normalize_symbol(symbol)
        if norm_sym in ["XAUUSD=X", "EURUSD=X"]:
            return self.yahoo_provider
        return self.binance_provider

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5") -> bool:
        norm_sym = normalize_symbol(symbol)
        norm_tf = normalize_timeframe(timeframe)
        
        try:
            provider = self._get_provider_for_symbol(norm_sym)
            provider_sym = SYMBOL_MAP.get(norm_sym, norm_sym)
            provider_tf = TIMEFRAME_MAP.get(norm_tf, "5m")

            raw_candles = await provider.fetch_klines(provider_sym, interval=provider_tf, limit=50)
            
            if not raw_candles:
                logger.warning(f"MARKET_DATA_EMPTY | Symbol: {norm_sym} | TF: {norm_tf}")
                self._update_health(norm_sym, norm_tf, status="UNAVAILABLE", error="Empty candle response")
                return False

            # Normalize & Validate Candles
            normalized_candles = []
            for c in raw_candles:
                normalized_candles.append({
                    "timestamp": c["timestamp"],
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c.get("volume", 0.0)),
                    "is_closed": bool(c.get("is_closed", True))
                })

            if norm_sym not in self._store:
                self._store[norm_sym] = {}
            self._store[norm_sym][norm_tf] = normalized_candles

            self._update_health(norm_sym, norm_tf, status="OK", error=None)
            logger.info(f"MARKET_DATA_OK | Symbol: {norm_sym} | TF: {norm_tf} | Candles: {len(normalized_candles)}")
            return True

        except Exception as e:
            logger.error(f"MARKET_DATA_ERROR | Symbol: {norm_sym} | Error: {str(e)}")
            self._update_health(norm_sym, norm_tf, status="ERROR", error=str(e))
            return False

    def get_candles(self, symbol: str, timeframe: str = "M5", limit: int = 50) -> List[Dict[str, Any]]:
        """Canonical Interface: Retreives normalized candle array."""
        norm_sym = normalize_symbol(symbol)
        norm_tf = normalize_timeframe(timeframe)
        candles = self._store.get(norm_sym, {}).get(norm_tf, [])
        return candles[-limit:]

    def get_latest_closed_candle(self, symbol: str, timeframe: str = "M5") -> Optional[Dict[str, Any]]:
        """Canonical Interface: Retrieves latest closed candle."""
        candles = self.get_candles(symbol, timeframe)
        closed = [c for c in candles if c.get("is_closed", True)]
        return closed[-1] if closed else None

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Canonical Interface: Retrieves latest ticker quote."""
        norm_sym = normalize_symbol(symbol)
        provider = self._get_provider_for_symbol(norm_sym)
        provider_sym = SYMBOL_MAP.get(norm_sym, norm_sym)
        return await provider.fetch_quote(provider_sym)

    def _update_health(self, symbol: str, timeframe: str, status: str, error: Optional[str]):
        key = f"{symbol}_{timeframe}"
        self._health_status[key] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": status,
            "last_error": error,
            "last_success": datetime.now(timezone.utc).isoformat() if status == "OK" else self._health_status.get(key, {}).get("last_success"),
            "data_age_seconds": 0 if status == "OK" else None
        }

    def get_health() -> Dict[str, Any]:
        return self._health_status

market_service = MarketDataService()
