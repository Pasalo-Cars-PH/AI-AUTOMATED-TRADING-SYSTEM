import os
import httpx
import datetime
from typing import List, Optional
from app.market.base_provider import MarketDataProvider
from app.market.models import Candle, Quote, ProviderStatus, DataQuality

FX_SYMBOL_MAP = {
    "XAUUSD": "XAU/USD", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD",
    "USDCHF": "USD/CHF", "NZDUSD": "NZD/USD"
}

TIMEFRAME_MAP = {
    "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
    "H1": "1h", "H4": "4h", "D1": "1day"
}

class TwelveDataProvider(MarketDataProvider):
    def __init__(self):
        super().__init__(name="TWELVEDATA")
        self.api_key = os.getenv("TWELVEDATA_API_KEY", "")
        self.base_url = "https://api.twelvedata.com"
        self.client = httpx.AsyncClient(timeout=10.0)

    async def connect(self) -> bool:
        if not self.api_key:
            self.status = ProviderStatus.MISCONFIGURED
            return False
        status = await self.health_check()
        return status in [ProviderStatus.CONNECTED, ProviderStatus.DEGRADED]

    async def health_check(self) -> ProviderStatus:
        if not self.api_key:
            self.status = ProviderStatus.MISCONFIGURED
            return self.status
        try:
            res = await self.client.get(f"{self.base_url}/api_usage", params={"apikey": self.api_key})
            if res.status_code == 200:
                self.status = ProviderStatus.CONNECTED
                self.last_success = datetime.datetime.utcnow().isoformat() + "Z"
            else:
                self.status = ProviderStatus.DEGRADED
        except Exception:
            self.status = ProviderStatus.UNAVAILABLE
            self.last_failure = datetime.datetime.utcnow().isoformat() + "Z"
            self.error_count += 1
        return self.status

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        p_symbol = FX_SYMBOL_MAP.get(symbol, symbol)
        if not self.api_key: return None
        try:
            res = await self.client.get(
                f"{self.base_url}/quote",
                params={"symbol": p_symbol, "apikey": self.api_key}
            )
            if res.status_code == 200:
                data = res.json()
                if "close" in data:
                    close_price = float(data["close"])
                    return Quote(
                        symbol=symbol,
                        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                        bid=None,
                        ask=None,
                        mid=close_price,
                        spread=None,
                        source=self.name,
                        provider_symbol=p_symbol,
                        quality=DataQuality.CONFIRMED_DATA
                    )
        except Exception:
            self.error_count += 1
        return None

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 50) -> List[Candle]:
        p_symbol = FX_SYMBOL_MAP.get(symbol, symbol)
        interval = TIMEFRAME_MAP.get(timeframe, "5min")
        if not self.api_key: return []
        candles = []
        try:
            res = await self.client.get(
                f"{self.base_url}/time_series",
                params={"symbol": p_symbol, "interval": interval, "outputsize": limit, "apikey": self.api_key}
            )
            if res.status_code == 200:
                data = res.json()
                if "values" in data:
                    for item in reversed(data["values"]):
                        candle = Candle(
                            symbol=symbol,
                            timestamp=item["datetime"] + "Z",
                            timeframe=timeframe,
                            open=float(item["open"]),
                            high=float(item["high"]),
                            low=float(item["low"]),
                            close=float(item["close"]),
                            volume=float(item.get("volume", 0)),
                            source=self.name,
                            provider_symbol=p_symbol,
                            is_closed=True,
                            quality=DataQuality.CONFIRMED_DATA
                        )
                        candles.append(candle)
        except Exception:
            self.error_count += 1
        return candles
