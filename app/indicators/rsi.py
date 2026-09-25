from typing import List, Optional
import pandas as pd
import ta
from app.data.normalizer import MarketCandle
from app.indicators.base import IndicatorResult

class RSIIndicator:
    @staticmethod
    def calculate(candles: List[MarketCandle], window: int = 14) -> Optional[IndicatorResult]:
        if not candles or len(candles) < window:
            return None

        df = pd.DataFrame([c.dict() for c in candles])
        rsi_series = ta.momentum.rsi(close=df['close'], window=window)
        latest_candle = candles[-1]

        return IndicatorResult(
            indicator_name="RSI_14",
            value=float(rsi_series.iloc[-1]),
            timestamp=latest_candle.timestamp,
            timeframe=latest_candle.timeframe,
            asset=latest_candle.symbol,
            data_source=latest_candle.source,
            calculated=True
        )
