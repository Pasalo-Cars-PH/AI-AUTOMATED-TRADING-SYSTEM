from typing import List, Optional
from pydantic import BaseModel
from app.data.normalizer import MarketCandle
from app.structure.swings import SwingDetector, SwingPoint, SwingType, StructureTag

class MarketStructureResult(BaseModel):
    current_trend: str  # BULLISH, BEARISH, NEUTRAL
    last_bos: Optional[str] = None
    last_choch: Optional[str] = None
    is_liquidity_sweep: bool = False
    sweep_detail: Optional[str] = None

class MarketStructureEngine:
    @staticmethod
    def analyze(candles: List[MarketCandle]) -> MarketStructureResult:
        if len(candles) < 20:
            return MarketStructureResult(current_trend="NEUTRAL")

        swings = SwingDetector.detect_swings(candles)
        if not swings:
            return MarketStructureResult(current_trend="NEUTRAL")

        latest_candle = candles[-1]
        swing_highs = [s for s in swings if s.swing_type == SwingType.SWING_HIGH]
        swing_lows = [s for s in swings if s.swing_type == SwingType.SWING_LOW]

        trend = "NEUTRAL"
        if swings[-1].tag in [StructureTag.HH, StructureTag.HL]:
            trend = "BULLISH"
        elif swings[-1].tag in [StructureTag.LH, StructureTag.LL]:
            trend = "BEARISH"

        bos = None
        choch = None

        # Check for BOS / CHOCH
        if swing_highs and latest_candle.close > swing_highs[-1].price:
            if trend == "BULLISH":
                bos = f"BULLISH BOS @ {swing_highs[-1].price:.2f}"
            else:
                choch = f"BULLISH CHOCH @ {swing_highs[-1].price:.2f}"
                trend = "BULLISH"

        elif swing_lows and latest_candle.close < swing_lows[-1].price:
            if trend == "BEARISH":
                bos = f"BEARISH BOS @ {swing_lows[-1].price:.2f}"
            else:
                choch = f"BEARISH CHOCH @ {swing_lows[-1].price:.2f}"
                trend = "BEARISH"

        # Check Liquidity Sweep (Wick break but close inside)
        is_sweep = False
        sweep_detail = None
        if swing_highs and latest_candle.high > swing_highs[-1].price and latest_candle.close <= swing_highs[-1].price:
            is_sweep = True
            sweep_detail = f"BUY-SIDE LIQUIDITY SWEEP @ {swing_highs[-1].price:.2f}"
        elif swing_lows and latest_candle.low < swing_lows[-1].price and latest_candle.close >= swing_lows[-1].price:
            is_sweep = True
            sweep_detail = f"SELL-SIDE LIQUIDITY SWEEP @ {swing_lows[-1].price:.2f}"

        return MarketStructureResult(
            current_trend=trend,
            last_bos=bos,
            last_choch=choch,
            is_liquidity_sweep=is_sweep,
            sweep_detail=sweep_detail
        )
