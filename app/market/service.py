# app/market/service.py
import logging
from typing import Dict, List, Optional, Any
from app.market.models import Candle, CandleDataState
from app.market.binance_provider import BinanceProvider
from app.market.twelvedata_provider import TwelveDataProvider

logger = logging.getLogger("trading_bot")

class MarketDataService:
    def __init__(self, binance_provider: Optional[BinanceProvider] = None, twelvedata_provider: Optional[TwelveDataProvider] = None):
        self.binance = binance_provider or BinanceProvider()
        self.twelvedata = twelvedata_provider or TwelveDataProvider()
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
        clean_symbol = self.normalize_symbol(symbol)
        if clean_symbol in self._cache and timeframe in self._cache[clean_symbol]:
            return self._cache[clean_symbol][timeframe]
        
        # Fallback fetch kung wala pa sa cache
        provider, clean = self._get_provider_for_symbol(clean_symbol)
        candles = await provider.get_candles(clean, timeframe, limit)
        
        if clean not in self._cache:
            self._cache[clean] = {}
        self._cache[clean][timeframe] = candles
        return candles

    async def update_symbol_data(self, symbol: str, timeframe: str = "M5") -> bool:
        try:
            clean_symbol = self.normalize_symbol(symbol)
            provider, clean = self._get_provider_for_symbol(clean_symbol)
            
            # Kumuha ng totoong candle data mula sa tamang provider
            candles = await provider.get_candles(clean, timeframe, limit=50)
            if not candles:
                logger.warning(f"MARKET_DATA_FETCH_EMPTY | Symbol: {clean_symbol}")
                return False

            if clean_symbol not in self._cache:
                self._cache[clean_symbol] = {}
            self._cache[clean_symbol][timeframe] = candles
            return True
        except Exception as e:
            logger.error(f"MARKET_DATA_UPDATE_ERROR | Symbol: {symbol} | Error: {e}")
            return False

market_service = MarketDataService()
