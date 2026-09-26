# app/market/service.py
import logging
from typing import Dict, List, Optional, Any
from app.market.models import Candle, CandleDataState
from app.market.binance_provider import BinanceProvider
from app.market.twelvedata_provider import TwelveDataProvider

logger = logging.getLogger("trading_bot")

class MarketDataService:
    def __init__(self, binance_provider: BinanceProvider, twelvedata_provider: TwelveDataProvider):
        self.binance = binance_provider
        self.twelvedata = twelvedata_provider
        self._cache: Dict[str, Dict[str, List[Candle]]] = {}

        self.crypto_symbols = {"BTCUSD", "ETHUSD", "SOLUSD"}
        self.fx_metal_symbols = {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"}

    def normalize_symbol(self, raw_symbol: str) -> str:
        s = raw_symbol.upper().replace("=X", "").replace("-USD", "USD")
        if s in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
            s = s.replace("USDT", "USD")
        return s

    def _get_provider_for_symbol(self, raw_symbol: str):
        symbol = self.normalize_symbol(raw_symbol)
        if symbol in self.crypto_symbols:
            return self.binance, symbol
        elif symbol in self.fx_metal_symbols:
            return self.twelvedata, symbol
        else:
            raise ValueError(f"UNSUPPORTED_SYMBOL | No provider mapped for symbol: {raw_symbol}")

    async def get_candles(self, symbol: str, timeframe: str = "M5", limit: int = 50) -> List[Candle]:
        provider, clean_symbol = self._get_provider_for_symbol(symbol)
        return await provider.get_candles(clean_symbol, timeframe, limit)

    async def get_latest_closed_candle(self, symbol: str, timeframe: str = "M5") -> Optional[Candle]:
        candles = await self.get_candles(symbol, timeframe, limit=5)
        for candle in reversed(candles):
            if candle.is_closed:
                return candle
        return None

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5") -> CandleDataState:
        try:
            candles = await self.get_candles(symbol, timeframe=timeframe, limit=50)
            if not candles:
                return CandleDataState.UNAVAILABLE_DATA
            return CandleDataState.CONFIRMED_DATA
        except Exception as e:
            logger.error(f"MARKET_DATA_ERROR | Symbol: {symbol} | Error: {e}")
            return CandleDataState.UNAVAILABLE_DATA
