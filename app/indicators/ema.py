from typing import List, Dict
import pandas as pd
import ta
from app.data.normalizer import MarketCandle
from app.indicators.base import IndicatorResult

class EMAIndicator:
    @staticmethod
    def calculate(candles: List[MarketCandle], windows: List[int] = [20, 50, 100, 200]) -> Dict[str, IndicatorResult]:
        if not candles or len(candles) < max(windows):
            return {}

        df = pd.DataFrame([c.dict() for c in candles])
        latest_candle = candles[-1]
        results = {}

        for window in windows:
            ema_series = ta.trend.ema_indicator(close=df['close'], window=window)
            results[f"EMA_{window}"] = IndicatorResult(
                indicator_name=f"EMA_{window}",
                value=float(ema_series.iloc[-1]),
                timestamp=latest_candle.timestamp,
                timeframe=latest_candle.timeframe,
                asset=latest_candle.symbol,
                data_source=latest_candle.source,
                calculated=True
            )
        return results
