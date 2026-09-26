import os
import aiohttp
import logging
from typing import List
from app.market.models import Candle

logger = logging.getLogger("trading_bot")

class TwelveDataProvider:
    def __init__(self):
        self.api_key = os.getenv("TWELVEDATA_API_KEY", "")
        self.base_url = "https://api.twelvedata.com/time_series"

    def _format_symbol(self, symbol: str) -> str:
        clean = symbol.upper().replace("=X", "").replace("-USD", "USD")
        # I-convert ang XAUUSD -> XAU/USD at EURUSD -> EUR/USD para sa TwelveData API
        if "/" not in clean and len(clean) == 6:
            return f"{clean[:3]}/{clean[3:]}"
        return clean

    async def get_candles(self, symbol: str, timeframe: str = "M5", limit: int = 50) -> List[Candle]:
        if not self.api_key:
            logger.warning(f"TWELVEDATA_NO_API_KEY | Missing key for symbol {symbol}")
            return []

        formatted_symbol = self._format_symbol(symbol)
        # Mapping timeframe: M5 -> 5min
        interval = "5min" if timeframe.upper() in ["M5", "5M"] else timeframe.lower()

        params = {
            "symbol": formatted_symbol,
            "interval": interval,
            "outputsize": limit,
            "apikey": self.api_key
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params) as resp:
                    data = await resp.json()

                    if resp.status != 200 or "values" not in data:
                        logger.warning(f"TWELVEDATA_FETCH_FAILED | Symbol: {symbol} ({formatted_symbol}) | Response: {data.get('message', 'No data')}")
                        return []

                    candles = []
                    for item in reversed(data["values"]):
                        # Convert datetime string to timestamp
                        dt_str = item["datetime"]
                        import datetime
                        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S" if len(dt_str) > 10 else "%Y-%m-%d")
                        ts = int(dt.timestamp())

                        candles.append(Candle(
                            timestamp=ts,
                            open=float(item["open"]),
                            high=float(item["high"]),
                            low=float(item["low"]),
                            close=float(item["close"]),
                            volume=float(item.get("volume", 0.0)),
                            symbol=symbol,
                            provider_symbol=formatted_symbol,
                            timeframe=timeframe,
                            source="twelvedata",
                            provider="twelvedata"
                        ))
                    return candles

        except Exception as e:
            logger.error(f"TWELVEDATA_EXCEPTION | Symbol: {symbol} | Error: {e}")
            return []
