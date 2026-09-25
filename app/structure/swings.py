from typing import List
from enum import Enum
from pydantic import BaseModel
from app.data.normalizer import MarketCandle

class SwingType(str, Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"

class StructureTag(str, Enum):
    HH = "HH"  # Higher High
    HL = "HL"  # Higher Low
    LH = "LH"  # Lower High
    LL = "LL"  # Lower Low

class SwingPoint(BaseModel):
    candle_index: int
    price: float
    timestamp: str
    swing_type: SwingType
    tag: StructureTag

class SwingDetector:
    @staticmethod
    def detect_swings(candles: List[MarketCandle], left: int = 2, right: int = 2) -> List[SwingPoint]:
        swings = []
        n = len(candles)
        if n < (left + right + 1):
            return swings

        prev_high = None
        prev_low = None

        for i in range(left, n - right):
            current = candles[i]
            
            # Check Swing High
            is_high = all(current.high >= candles[i - j].high for j in range(1, left + 1)) and \
                      all(current.high > candles[i + j].high for j in range(1, right + 1))
            
            # Check Swing Low
            is_low = all(current.low <= candles[i - j].low for j in range(1, left + 1)) and \
                     all(current.low < candles[i + j].low for j in range(1, right + 1))

            if is_high:
                tag = StructureTag.HH if (prev_high is None or current.high > prev_high) else StructureTag.LH
                prev_high = current.high
                swings.append(SwingPoint(
                    candle_index=i,
                    price=current.high,
                    timestamp=current.timestamp.isoformat(),
                    swing_type=SwingType.SWING_HIGH,
                    tag=tag
                ))

            elif is_low:
                tag = StructureTag.HL if (prev_low is None or current.low > prev_low) else StructureTag.LL
                prev_low = current.low
                swings.append(SwingPoint(
                    candle_index=i,
                    price=current.low,
                    timestamp=current.timestamp.isoformat(),
                    swing_type=SwingType.SWING_LOW,
                    tag=tag
                ))

        return swings
