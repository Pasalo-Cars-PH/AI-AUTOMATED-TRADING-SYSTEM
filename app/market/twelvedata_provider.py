import os
import requests
import asyncio
import logging
from datetime import datetime
from typing import List
from app.market.models import Candle

logger = logging.getLogger("trading_bot")

class TwelveDataProvider:
    def __init__(self):
        # Babasahin ang key kahit ano pa ang eksaktong spelling sa Render Environment
        self.api_key = os.getenv("TWELVEDATA_API_KEY") or os.getenv("TWELVEDATE_API_KEY") or ""
        self.base_url = "https://api.twelvedata.com/time_series"

    def _format_symbol(self, symbol: str) -> str:
        clean = symbol.upper().replace("=X", "").replace("-USD", "USD")
        if "/" not in clean and len(clean) == 6:
            return f"{clean[:3]}/{clean[3:]}"
        return clean

    def _fetch_sync(self, params: dict) -> dict:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(self.base_url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        return {}

    async def get_candles(self, symbol: str, timeframe: str = "M5", limit: int = 50) -> List[Candle]:
        api_key = self.api_key or os.getenv("TWELVEDATA_API_KEY") or os.getenv("TWELVEDATE_API_KEY") or ""
        if not api_key:
            logger.warning(f"TWELVEDATA_NO_API_KEY | Missing key for symbol {symbol}")
            return []

        formatted_symbol = self._format_symbol(symbol)
        interval = "5min" if timeframe.upper() in ["M5", "5M"] else timeframe.lower()

        params = {
            "symbol": formatted_symbol,
            "interval": interval,
            "outputsize": limit,
            "apikey": api_key
        }

        try:
            data = await asyncio.to_thread(self._fetch_sync, params)

            if not data or "values" not in data:
                logger.warning(f"TWELVEDATA_FETCH_FAILED | Symbol: {symbol} ({formatted_symbol}) | Message: {data.get('message', 'No values')}")
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
