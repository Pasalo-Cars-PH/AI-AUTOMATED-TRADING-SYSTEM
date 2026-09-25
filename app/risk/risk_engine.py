from pydantic import BaseModel
from typing import Optional, List, Dict
from app.risk.correlation import CorrelationEngine

class PositionSizingResult(BaseModel):
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_distance: float
    risk_reward_ratio: float
    position_size: float
    risk_amount_usd: float
    is_valid: bool
    rejection_reason: Optional[str] = None

class RiskEngine:
    DEFAULT_RISK_PCT = 0.005  # 0.5%
    MAX_RISK_PCT = 0.010      # 1.0%
    MIN_RR_RATIO = 1.5

    @staticmethod
    def calculate_position(
        account_equity: float,
        entry: float,
        stop_loss: float,
        direction: str,
        symbol: str,
        active_positions: List[Dict],
        atr: float,
        contract_size: float = 1.0
    ) -> PositionSizingResult:
        if account_equity <= 0:
            return PositionSizingResult(
                entry_price=entry, stop_loss=stop_loss, take_profit=0,
                risk_distance=0, risk_reward_ratio=0, position_size=0,
                risk_amount_usd=0, is_valid=False, rejection_reason="Invalid Account Equity"
            )

        # Dynamic Stop Loss enforcement (larger of structure SL or 1.5x ATR)
        atr_sl_dist = atr * 1.5
        calc_sl_dist = abs(entry - stop_loss)
        effective_sl_dist = max(calc_sl_dist, atr_sl_dist)

        if direction == "LONG":
            effective_sl = entry - effective_sl_dist
            take_profit = entry + (effective_sl_dist * 2.0)  # 1:2 R:R default target
        else:
            effective_sl = entry + effective_sl_dist
            take_profit = entry - (effective_sl_dist * 2.0)

        risk_reward = abs(take_profit - entry) / effective_sl_dist

        if risk_reward < RiskEngine.MIN_RR_RATIO:
            return PositionSizingResult(
                entry_price=entry, stop_loss=effective_sl, take_profit=take_profit,
                risk_distance=effective_sl_dist, risk_reward_ratio=risk_reward,
                position_size=0, risk_amount_usd=0, is_valid=False,
                rejection_reason=f"Risk/Reward {risk_reward:.2f} below minimum threshold {RiskEngine.MIN_RR_RATIO}"
            )

        # Correlation Check
        if not CorrelationEngine.validate_correlation(symbol, direction, active_positions):
            return PositionSizingResult(
                entry_price=entry, stop_loss=effective_sl, take_profit=take_profit,
                risk_distance=effective_sl_dist, risk_reward_ratio=risk_reward,
                position_size=0, risk_amount_usd=0, is_valid=False,
                rejection_reason=f"Correlated Risk Bucket limit exceeded for {symbol}"
            )

        # Position Sizing Calculation
        risk_amount_usd = account_equity * RiskEngine.DEFAULT_RISK_PCT
        position_size = risk_amount_usd / (effective_sl_dist * contract_size)

        return PositionSizingResult(
            entry_price=entry,
            stop_loss=effective_sl,
            take_profit=take_profit,
            risk_distance=effective_sl_dist,
            risk_reward_ratio=risk_reward,
            position_size=round(position_size, 4),
            risk_amount_usd=round(risk_amount_usd, 2),
            is_valid=True
        )
