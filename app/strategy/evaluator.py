from typing import List, Dict, Any, Optional
from app.market.models import Candle
from app.strategy.indicators import calculate_ema, calculate_rsi, calculate_atr

class StrategyEvaluator:
    def __init__(self, min_score_threshold: int = 70):
        self.min_score_threshold = min_score_threshold

    def evaluate_m5_setup(self, symbol: str, candles: List[Candle]) -> Dict[str, Any]:
        if len(candles) < 30:
            return {"action": "HOLD", "score": 0, "reason": "Insufficient candle data"}

        closes = [c.close for c in candles]
        latest_close = closes[-1]

        ema_20 = calculate_ema(closes, 20)
        ema_50 = calculate_ema(closes, 50) if len(closes) >= 50 else calculate_ema(closes, 30)
        rsi_14 = calculate_rsi(closes, 14)
        atr_14 = calculate_atr(candles, 14)

        if not ema_20 or not rsi_14 or not atr_14:
            return {"action": "HOLD", "score": 0, "reason": "Failed to compute indicators"}

        score = 0
        reasons = []
        action = "HOLD"

        # Check Bullish Confluence
        if latest_close > ema_20:
            score += 30
            reasons.append("Price above EMA20 (+30)")

        if ema_50 and ema_20 > ema_50:
            score += 25
            reasons.append("EMA20 > EMA50 Trend (+25)")

        if 45 <= rsi_14 <= 65:
            score += 25
            reasons.append(f"RSI Momentum healthy ({round(rsi_14, 1)}) (+25)")
        elif rsi_14 < 30:
            score += 20
            reasons.append(f"RSI Oversold reversal setup ({round(rsi_14, 1)}) (+20)")

        # Candlestick Pattern / Momentum
        prev_candle = candles[-2]
        latest_candle = candles[-1]
        if latest_candle.close > latest_candle.open and latest_candle.close > prev_candle.high:
            score += 20
            reasons.append("Bullish Breakout/Engulfing Candle (+20)")

        if score >= self.min_score_threshold:
            action = "BUY"

        # Bearish Confluence Check
        bearish_score = 0
        bearish_reasons = []

        if latest_close < ema_20:
            bearish_score += 30
            bearish_reasons.append("Price below EMA20 (+30)")

        if ema_50 and ema_20 < ema_50:
            bearish_score += 25
            bearish_reasons.append("EMA20 < EMA50 Downtrend (+25)")

        if 35 <= rsi_14 <= 55:
            bearish_score += 25
            bearish_reasons.append(f"RSI Bearish Momentum ({round(rsi_14, 1)}) (+25)")
        elif rsi_14 > 70:
            bearish_score += 20
            bearish_reasons.append(f"RSI Overbought reversal setup ({round(rsi_14, 1)}) (+20)")

        if latest_candle.close < latest_candle.open and latest_candle.close < prev_candle.low:
            bearish_score += 20
            bearish_reasons.append("Bearish Engulfing Candle (+20)")

        if bearish_score > score and bearish_score >= self.min_score_threshold:
            action = "SELL"
            score = bearish_score
            reasons = bearish_reasons

        # Calculate Stop Loss and Take Profit levels based on ATR
        sl_distance = atr_14 * 1.5
        tp_distance = atr_14 * 3.0

        sl_price = round(latest_close - sl_distance if action == "BUY" else latest_close + sl_distance, 2)
        tp_price = round(latest_close + tp_distance if action == "BUY" else latest_close - tp_distance, 2)

        return {
            "symbol": symbol,
            "action": action,
            "score": score,
            "threshold": self.min_score_threshold,
            "latest_price": latest_close,
            "indicators": {
                "ema_20": round(ema_20, 2),
                "ema_50": round(ema_50, 2) if ema_50 else None,
                "rsi_14": round(rsi_14, 2),
                "atr_14": round(atr_14, 2)
            },
            "trade_parameters": {
                "stop_loss": sl_price if action != "HOLD" else None,
                "take_profit": tp_price if action != "HOLD" else None,
                "risk_reward_ratio": "1:2"
            },
            "reasons": reasons
        }

strategy_evaluator = StrategyEvaluator(min_score_threshold=70)
