from typing import List, Optional
from app.data.normalizer import MarketCandle
from app.indicators.base import IndicatorResult
from app.structure.market_structure import MarketStructureResult
from app.strategies.base import CandidateSetup, TradeDirection

class SetupEngine:
    @staticmethod
    def evaluate_setups(
        candles: List[MarketCandle],
        indicators: dict,
        structure: MarketStructureResult
    ) -> Optional[CandidateSetup]:
        if not candles or "EMA_200" not in indicators or "RSI_14" not in indicators:
            return None

        current_price = candles[-1].close
        ema_200 = indicators["EMA_200"].value
        rsi = indicators["RSI_14"].value
        atr = indicators["ATR_14"].value if "ATR_14" in indicators else 10.0

        # Strategy A: Trend Continuation / Pullback
        if structure.current_trend == "BULLISH" and current_price > ema_200 and rsi < 45:
            return CandidateSetup(
                strategy_name="Trend Continuation Pullback",
                direction=TradeDirection.LONG,
                confidence=0.85,
                trigger_level=current_price,
                setup_zone_high=current_price + (atr * 0.5),
                setup_zone_low=current_price - (atr * 0.5),
                invalidation_level=current_price - (atr * 1.5),
                reasoning=["Price above 200 EMA (Bullish)", "Market Structure: BULLISH", "RSI Pullback to oversold zone"]
            )

        elif structure.current_trend == "BEARISH" and current_price < ema_200 and rsi > 55:
            return CandidateSetup(
                strategy_name="Trend Continuation Pullback",
                direction=TradeDirection.SHORT,
                confidence=0.85,
                trigger_level=current_price,
                setup_zone_high=current_price + (atr * 0.5),
                setup_zone_low=current_price - (atr * 0.5),
                invalidation_level=current_price + (atr * 1.5),
                reasoning=["Price below 200 EMA (Bearish)", "Market Structure: BEARISH", "RSI Rally to overbought zone"]
            )

        # Strategy C: Liquidity Sweep Reaction
        elif structure.is_liquidity_sweep and structure.sweep_detail:
            direction = TradeDirection.SHORT if "BUY-SIDE" in structure.sweep_detail else TradeDirection.LONG
            invalidation = current_price + (atr * 1.0) if direction == TradeDirection.SHORT else current_price - (atr * 1.0)
            return CandidateSetup(
                strategy_name="Liquidity Sweep Reversal",
                direction=direction,
                confidence=0.90,
                trigger_level=current_price,
                setup_zone_high=current_price + (atr * 0.2),
                setup_zone_low=current_price - (atr * 0.2),
                invalidation_level=invalidation,
                reasoning=[structure.sweep_detail, "Institutional liquidity grab detected"]
            )

        return None
