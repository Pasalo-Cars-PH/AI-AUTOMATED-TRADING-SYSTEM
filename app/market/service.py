import logging
import httpx
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger("trading_bot")

SYMBOL_MAP = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "SOLUSD": "SOLUSDT",
    "XAUUSD=X": "PAXGUSDT",  # Ginagamit ang PAXG/USDT bilang 1:1 Gold proxy sa Binance
    "EURUSD=X": "EURUSDT"    # Ginagamit ang EUR/USDT sa Binance
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
        self._store: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        self._health_status: Dict[str, Dict[str, Any]] = {}

    async def fetch_binance_klines(self, binance_symbol: str, interval: str = "5m", limit: int = 50) -> List[Dict[str, Any]]:
        url = f"https://api.binance.com/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code != 200:
                raise Exception(f"Binance API status {resp.status_code}: {resp.text}")
            
            data = resp.json()
            candles = []
            for item in data:
                candles.append({
                    "timestamp": int(item[0]),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "is_closed": True
                })
            return candles

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5") -> bool:
        norm_sym = normalize_symbol(symbol)
        norm_tf = normalize_timeframe(timeframe)
        
        try:
            binance_sym = SYMBOL_MAP.get(norm_sym, norm_sym.replace("USD", "USDT"))
            interval = TIMEFRAME_MAP.get(norm_tf, "5m")

            normalized_candles = await self.fetch_binance_klines(binance_sym, interval=interval, limit=50)
            
            if not normalized_candles:
                logger.warning(f"MARKET_DATA_EMPTY | Symbol: {norm_sym} | TF: {norm_tf}")
                self._update_health(norm_sym, norm_tf, status="UNAVAILABLE", error="Empty response")
                return False

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
        norm_sym = normalize_symbol(symbol)
        norm_tf = normalize_timeframe(timeframe)
        candles = self._store.get(norm_sym, {}).get(norm_tf, [])
        return candles[-limit:]

    def get_latest_closed_candle(self, symbol: str, timeframe: str = "M5") -> Optional[Dict[str, Any]]:
        candles = self.get_candles(symbol, timeframe)
        closed = [c for c in candles if c.get("is_closed", True)]
        return closed[-1] if closed else None

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        norm_sym = normalize_symbol(symbol)
        binance_sym = SYMBOL_MAP.get(norm_sym, norm_sym.replace("USD", "USDT"))
        url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={binance_sym}"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "symbol": norm_sym,
                    "bid": float(data["bidPrice"]),
                    "ask": float(data["askPrice"]),
                    "price": (float(data["bidPrice"]) + float(data["askPrice"])) / 2
                }
            return {}

    def _update_health(self, symbol: str, timeframe: str, status: str, error: Optional[str]):
        key = f"{symbol}_{timeframe}"
        self._health_status[key] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": status,
            "last_error": error,
            "last_success": datetime.now(timezone.utc).isoformat() if status == "OK" else self._health_status.get(key, {}).get("last_success")
        }

    def get_health(self) -> Dict[str, Any]:
        return self._health_status

market_service = MarketDataService()
