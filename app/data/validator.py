from typing import List
from app.data.normalizer import MarketCandle, DataQualityState

class DataValidator:
    @staticmethod
    def validate_candles(candles: List[MarketCandle]) -> DataQualityState:
        if not candles or len(candles) == 0:
            return DataQualityState.UNAVAILABLE_DATA

        for c in candles:
            # Check for negative or zero prices
            if c.open <= 0 or c.high <= 0 or c.low <= 0 or c.close <= 0:
                return DataQualityState.MISSING_DATA
            
            # Check for corrupted OHLC structure
            if c.high < c.low or c.high < c.open or c.high < c.close or c.low > c.open or c.low > c.close:
                return DataQualityState.MISSING_DATA

        return DataQualityState.CONFIRMED_DATA
