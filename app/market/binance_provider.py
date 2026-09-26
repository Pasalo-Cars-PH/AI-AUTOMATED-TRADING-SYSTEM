import httpx
import datetime
import logging
from typing import List, Optional
from app.market.base_provider import MarketDataProvider
from app.market.models import Candle, Quote, ProviderStatus, DataQuality

logger = logging.getLogger("trading_bot")

BINANCE_SYMBOL_MAP = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "SOLUSD": "SOLUSDT",
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
    "SOLUSDT": "SOLUSDT"
}

TIMEFRAME_MAP = {
    "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
    "H1": "1h", "H4": "4h", "D1": "1d"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

class BinanceProvider(MarketDataProvider):
    def __init__(self):
        super().__init__(name="BINANCE")
        self.base_url = "https://api.binance.com/api/v3"

    async def connect(self) -> bool:
        status = await self.health_check()
        return status in [ProviderStatus.CONNECTED, ProviderStatus.DEGRADED]

    async def health_check(self) -> ProviderStatus:
        try:
            async with httpx.AsyncClient(timeout=5.0, headers=HEADERS) as client:
                res = await client.get(f"{self.base_url}/ping")
                if res.status_code == 200:
                    self.status = ProviderStatus.CONNECTED
                    self.last_success = datetime.datetime.utcnow().isoformat() + "Z"
                elif res.status_code in [429, 418]:
                    self.status = ProviderStatus.RATE_LIMITED
                    self.rate_limit_events += 1
                else:
                    self.status = ProviderStatus.DEGRADED
        except Exception as e:
            logger.error(f"Binance health_check error: {e}")
            self.status = ProviderStatus.UNAVAILABLE
            self.last_failure = datetime.datetime.utcnow().isoformat() + "Z"
            self.error_count += 1
        return self.status

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        p_symbol = BINANCE_SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        try:
            async with httpx.AsyncClient(timeout=5.0, headers=HEADERS) as client:
                res = await client.get(f"{self.base_url}/ticker/bookTicker", params={"symbol": p_symbol})
                if res.status_code == 200:
                    data = res.json()
                    bid = float(data["bidPrice"])
                    ask = float(data["askPrice"])
                    mid = (bid + ask) / 2.0
                    return Quote(
                        symbol=symbol.upper(),
                        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        spread=round(ask - bid, 8),
                        source=self.name,
                        provider_symbol=p_symbol,
                        quality=DataQuality.CONFIRMED_DATA
                    )
        except Exception as e:
            logger.error(f"Binance get_quote error for {symbol}: {e}")
            self.error_count += 1
        return None

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 50) -> List[Candle]:
        p_symbol = BINANCE_SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        interval = TIMEFRAME_MAP.get(timeframe.upper(), "5m")
        candles = []
        try:
            async with httpx.AsyncClient(timeout=5.0, headers=HEADERS) as client:
                res = await client.get(
                    f"{self.base_url}/klines",
                    params={"symbol": p_symbol, "interval": interval, "limit": limit}
                )
                if res.status_code == 200:
                    now_ms = datetime.datetime.utcnow().timestamp() * 1000
                    for item in res.json():
                        close_time = item[6]
                        is_closed = close_time < now_ms
                        candle = Candle(
                            symbol=symbol.upper(),
                            timestamp=datetime.datetime.utcfromtimestamp(item[0] / 1000.0).isoformat() + "Z",
                            timeframe=timeframe.upper(),
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[5]),
                            source=self.name,
                            provider_symbol=p_symbol,
                            is_closed=is_closed,
                            quality=DataQuality.CONFIRMED_DATA
                        )
                        candles.append(candle)
        except Exception as e:
            logger.error(f"Binance get_candles error for {symbol}: {e}")
            self.error_count += 1
        return candles
