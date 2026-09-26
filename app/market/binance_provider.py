import os
import re
import time
import requests
import asyncio
import logging
from typing import List
from app.market.models import Candle

logger = logging.getLogger("trading_bot")


class BinanceProvider:
    # Shared sa lahat ng instance/symbol sa process na 'to — pag na-ban tayo,
    # itigil muna LAHAT ng request papuntang Binance hanggang lumipas yung ban.
    # Kung hindi ito ihinto, patuloy na papatagalin ng bawat retry yung ban.
    _banned_until: float = 0.0
    _consecutive_failures: int = 0

    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3/klines"

    def _parse_ban_until(self, body: str) -> float:
        """I-extract yung 'banned until <ms epoch>' mula sa error body ng Binance."""
        match = re.search(r"banned until (\d+)", body)
        if match:
            return int(match.group(1)) / 1000.0
        return 0.0

    def _fetch_sync(self, url: str, params: dict) -> list:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            BinanceProvider._consecutive_failures = 0
            return response.json()

        logger.warning(f"BINANCE_FETCH_ERROR | Status: {response.status_code} | Body: {response.text}")

        if response.status_code in (418, 429):
            ban_ts = self._parse_ban_until(response.text)
            if ban_ts:
                BinanceProvider._banned_until = ban_ts
                logger.warning(f"BINANCE_BANNED | Pausing all Binance requests until epoch {ban_ts}")
            else:
                # Walang ban timestamp sa body — sariling exponential backoff na lang.
                BinanceProvider._consecutive_failures += 1
                cooldown = min(300, 10 * (2 ** BinanceProvider._consecutive_failures))
                BinanceProvider._banned_until = time.time() + cooldown
                logger.warning(f"BINANCE_BACKOFF | Cooling down for {cooldown}s")

        return []

    async def get_candles(self, symbol: str, timeframe: str = "M5", limit: int = 50) -> List[Candle]:
        # Kung naka-ban/cooldown pa tayo, wag muna gumawa ng bagong request.
        now = time.time()
        if now < BinanceProvider._banned_until:
            remaining = int(BinanceProvider._banned_until - now)
            logger.info(f"BINANCE_SKIP_BANNED | Symbol: {symbol} | {remaining}s pa bago mag-retry")
            return []

        try:
            clean_symbol = symbol.upper().replace("=X", "")
            if clean_symbol in ["BTCUSD", "ETHUSD", "SOLUSD"]:
                binance_symbol = clean_symbol.replace("USD", "USDT")
            else:
                binance_symbol = clean_symbol

            interval_map = {"M1": "1m", "M5": "5m", "M15": "15m", "H1": "1h", "D1": "1d"}
            interval = interval_map.get(timeframe.upper(), "5m")

            params = {
                "symbol": binance_symbol,
                "interval": interval,
                "limit": limit
            }

            data = await asyncio.to_thread(self._fetch_sync, self.base_url, params)

            if not data or not isinstance(data, list):
                return []

            candles = []
            for item in data:
                candles.append(Candle(
                    timestamp=int(item[0] // 1000),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    symbol=symbol,
                    provider_symbol=binance_symbol,
                    timeframe=timeframe,
                    source="binance",
                    provider="binance"
                ))
            return candles

        except Exception as e:
            logger.error(f"BINANCE_EXCEPTION | Symbol: {symbol} | Error: {e}")
            return []
