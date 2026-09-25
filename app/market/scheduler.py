import asyncio
import logging
from app.market.service import market_service

logger = logging.getLogger("market_scheduler")

ALL_SYMBOLS = [
    "BTCUSD", "ETHUSD", "SOLUSD",
    "XAUUSD", "EURUSD", "GBPUSD", "USDJPY",
    "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"
]

class MarketScheduler:
    def __init__(self):
        self._running = False
        self._lock = asyncio.Lock()

    async def start(self):
        if self._running:
            return
        self._running = True
        await market_service.initialize()
        asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        while self._running:
            async with self._lock:
                for symbol in ALL_SYMBOLS:
                    try:
                        await market_service.update_symbol_data(symbol, timeframe="M5")
                    except Exception as e:
                        logger.error(f"Error updating market data for {symbol}: {e}")
            await asyncio.sleep(60)

    def stop(self):
        self._running = False

market_scheduler = MarketScheduler()
