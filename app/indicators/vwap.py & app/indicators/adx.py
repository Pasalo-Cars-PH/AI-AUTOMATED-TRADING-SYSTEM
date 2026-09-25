# app/indicators/vwap.py
from typing import List, Optional
import pandas as pd
import ta
from app.data.normalizer import MarketCandle
from app.indicators.base import IndicatorResult

class VWAPIndicator:
    @staticmethod
    def calculate(candles: List[MarketCandle]) -> Optional[IndicatorResult]:
        if not candles or len(candles) < 14:
            return None
            
        df = pd.DataFrame([c.dict() for c in candles])
        vwap_series = ta.volume.volume_weighted_average_price(
            high=df['high'], low=df['low'], close=df['close'], volume=df['volume'], window=14
        )
        latest_candle = candles[-1]

        return IndicatorResult(
            indicator_name="VWAP",
            value=float(vwap_series.iloc[-1]),
            timestamp=latest_candle.timestamp,
            timeframe=latest_candle.timeframe,
            asset=latest_candle.symbol,
            data_source=latest_candle.source,
            calculated=True
        )

# app/indicators/adx.py
from typing import List, Optional
import pandas as pd
import ta
from app.data.normalizer import MarketCandle
from app.indicators.base import IndicatorResult

class ADXIndicator:
    @staticmethod
    def calculate(candles: List[MarketCandle], window: int = 14) -> Optional[IndicatorResult]:
        if not candles or len(candles) < window:
            return None

        df = pd.DataFrame([c.dict() for c in candles])
        adx_series = ta.trend.adx(
            high=df['high'], low=df['low'], close=df['close'], window=window
        )
        latest_candle = candles[-1]

        return IndicatorResult(
            indicator_name="ADX_14",
            value=float(adx_series.iloc[-1]),
            timestamp=latest_candle.timestamp,
            timeframe=latest_candle.timeframe,
            asset=latest_candle.symbol,
            data_source=latest_candle.source,
            calculated=True
        )
