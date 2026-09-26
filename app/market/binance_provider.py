import logging
import httpx
from typing import Optional, List, Dict, Any

logger = logging.getLogger("trading_bot")

class BinanceProvider:
    BASE_URL = "https://api.binance.com"

    SYMBOL_MAP = {
        "BTCUSD": "BTCUSDT",
        "ETHUSD": "ETHUSDT",
        "SOLUSD": "SOLUSDT",
        "BTCUSDT": "BTCUSDT",
        "ETHUSDT": "ETHUSDT",
        "SOLUSDT": "SOLUSDT",
    }

    TIMEFRAME_MAP = {
        "M1": "1m",
        "M5": "5m",
        "M15": "15m",
        "H1": "1h",
        "H4": "4h",
        "D1": "1d",
    }

    @classmethod
    def normalize_symbol(cls, symbol: str) -> str:
        clean = symbol.upper().replace("/", "").replace("-", "")
        return cls.SYMBOL_MAP.get(clean, clean)

    @classmethod
    async def fetch_quote(cls, symbol: str) -> Optional[Dict[str, Any]]:
        target_symbol = cls.normalize_symbol(symbol)
        url = f"{cls.BASE_URL}/api/v3/ticker/bookTicker?symbol={target_symbol}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    bid = float(data["bidPrice"])
                    ask = float(data["askPrice"])
                    return {
                        "symbol": symbol.upper(),
                        "bid": bid,
                        "ask": ask,
                        "price": (bid + ask) / 2.0,
                        "provider": "binance",
                    }
                else:
                    logger.warning(f"Binance fetch_quote failed for {target_symbol}: {resp.status_code}")
        except Exception as e:
            logger.error(f"Binance fetch_quote error for {target_symbol}: {e}")
        return None

    @classmethod
    async def fetch_candles(cls, symbol: str, timeframe: str = "M5", limit: int = 100) -> List[Dict[str, Any]]:
        target_symbol = cls.normalize_symbol(symbol)
        interval = cls.TIMEFRAME_MAP.get(timeframe.upper(), "5m")
        url = f"{cls.BASE_URL}/api/v3/klines?symbol={target_symbol}&interval={interval}&limit={limit}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    candles = []
                    for row in resp.json():
                        candles.append({
                            "timestamp": int(row[0]),
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "volume": float(row[5]),
                        })
                    return candles
        except Exception as e:
            logger.error(f"Binance fetch_candles error for {target_symbol}: {e}")
        return []
