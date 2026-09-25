from typing import Dict, List
from pydantic import BaseModel
from app.strategies.base import CandidateSetup, TradeDirection
from app.data.normalizer import DataQualityState

class ScoreBreakdown(BaseModel):
    trend: int = 0         # Max 15
    structure: int = 0     # Max 15
    momentum: int = 0     # Max 10
    price_action: int = 0  # Max 10
    volatility: int = 0    # Max 8
    sr_level: int = 0      # Max 10
    mtf_align: int = 0     # Max 12
    entry_quality: int = 0 # Max 10
    risk_reward: int = 0   # Max 5
    data_quality: int = 0  # Max 5
    total_score: int = 0
    score_band: str = "NO TRADE"
    is_actionable: bool = False

class ConfluenceEngine:
    MIN_ACTIONABLE_SCORE = 75

    @staticmethod
    def calculate_score(
        setup: CandidateSetup,
        indicators: dict,
        structure,
        mtf_score: int,
        rr_ratio: float,
        data_quality: DataQualityState
    ) -> ScoreBreakdown:
        b = ScoreBreakdown()

        # 1. Trend (15)
        if "EMA_200" in indicators:
            price = setup.trigger_level
            ema200 = indicators["EMA_200"].value
            if (setup.direction == TradeDirection.LONG and price > ema200) or \
               (setup.direction == TradeDirection.SHORT and price < ema200):
                b.trend = 15

        # 2. Structure (15)
        if structure.current_trend == setup.direction.value:
            b.structure = 15
        elif structure.is_liquidity_sweep:
            b.structure = 12

        # 3. Momentum (10)
        if "RSI_14" in indicators:
            rsi = indicators["RSI_14"].value
            if setup.direction == TradeDirection.LONG and 30 <= rsi <= 50:
                b.momentum = 10
            elif setup.direction == TradeDirection.SHORT and 50 <= rsi <= 70:
                b.momentum = 10

        # 4. Volatility & ADX (8)
        if "ADX_14" in indicators and indicators["ADX_14"].value > 20:
            b.volatility = 8

        # 5. MTF Alignment (12)
        b.mtf_align = min(12, max(0, mtf_score))

        # 6. Risk/Reward (5)
        if rr_ratio >= 2.0:
            b.risk_reward = 5
        elif rr_ratio >= 1.5:
            b.risk_reward = 3

        # 7. Data Quality (5)
        if data_quality == DataQualityState.CONFIRMED_DATA:
            b.data_quality = 5

        # Basic Entry Quality & S/R defaults for valid setups
        b.entry_quality = 8
        b.sr_level = 8
        b.price_action = 8

        b.total_score = (
            b.trend + b.structure + b.momentum + b.price_action +
            b.volatility + b.sr_level + b.mtf_align + b.entry_quality +
            b.risk_reward + b.data_quality
        )

        # Determine Score Band
        if b.total_score >= 85:
            b.score_band = "HIGH CONFLUENCE"
        elif b.total_score >= 75:
            b.score_band = "STRONG"
        elif b.total_score >= 65:
            b.score_band = "DEVELOPING"
        elif b.total_score >= 50:
            b.score_band = "WATCH"
        else:
            b.score_band = "NO TRADE"

        b.is_actionable = b.total_score >= ConfluenceEngine.MIN_ACTIONABLE_SCORE
        return b
