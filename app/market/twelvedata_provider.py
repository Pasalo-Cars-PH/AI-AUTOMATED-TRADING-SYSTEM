import os
import json
import logging
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime
from typing import List
from app.market.models import Candle

logger = logging.getLogger("trading_bot")

class TwelveDataProvider:
    def __init__(self):
        self.api_key = os.getenv("TWELVEDATA_API_KEY", "")
        self.base_url = "https://api.twelvedata.com/time_series"

    def _format_symbol(self, symbol: str) -> str:
        clean = symbol.upper().replace("=X", "").replace("-USD", "USD")
        if "/" not in clean and len(clean) == 6:
            return f"{clean[:3]}/{clean[3:]}"
        return clean

    def _fetch_sync(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
        return {}

    async def get_candles(self, symbol: str, timeframe: str = "M5", limit: int = 50) -> List[Candle]:
        if not self.api_key:
            logger.warning(f"TWELVEDATA_NO_API_KEY | Missing key for symbol {symbol}")
            return []

        formatted_symbol = self._format_symbol(symbol)
        interval = "5min" if timeframe.upper() in ["M5", "5M"] else timeframe.lower()

        params = {
            "symbol": formatted_symbol,
            "interval": interval,
            "outputsize": limit,
            "apikey": self.api_key
        }
        
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"

        try:
            # Gamitin ang asyncio.to_thread para hindi ma-block ang event loop
            data = await asyncio.to_thread(self._fetch_sync, url)

            if not data or "values" not in data:
                logger.warning(f"TWELVEDATA_FETCH_FAILED | Symbol: {symbol} ({formatted_symbol}) | Response: {data.get('message', 'No values returned')}")
                return []

            candles = []
            for item in reversed(data["values"]):
                dt_str = item["datetime"]
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S" if len(dt_str) > 10 else "%Y-%m-%d")
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
