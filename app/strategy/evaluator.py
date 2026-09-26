import logging
from typing import List, Dict, Any

logger = logging.getLogger("trading_bot")

class StrategyEvaluator:
    def calculate_atr(self, candles: List[Dict[str, Any]], period: int = 14) -> float:
        """Kina-calculate ang Average True Range (ATR) para sa volatility-based SL/TP."""
        if len(candles) < period + 1:
            return 0.0010  # Fallback minimum ATR

        tr_list = []
        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            prev_close = candles[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        return sum(tr_list[-period:]) / period

    def calculate_lot_size(self, balance: float, sl_distance: float, price: float, risk_pct: float = 0.01) -> float:
        """
        Kina-calculate ang dynamic lot size batay sa 1% risk per trade.
        """
        if balance <= 0 or sl_distance <= 0:
            return 0.01  # Safe minimum lot

        risk_amount = balance * risk_pct
        # Approximated standard pip/point value calculation
        lot_size = round(risk_amount / (sl_distance * 100000 / price), 2)
        
        # Min lot limit: 0.01 | Max lot safety cap: 0.50
        return max(0.01, min(lot_size, 0.50))

    def evaluate_m5_setup(self, symbol: str, candles: List[Dict[str, Any]], balance: float = 1000.0) -> Dict[str, Any]:
        """
        Sino-score ang M5 confluence at nag-ge-generate ng eksaktong SL, TP, at Lot Size.
        """
        if not candles or len(candles) < 20:
            return {"action": "HOLD", "score": 0, "reason": "Insufficient candles"}

        latest = candles[-1]
        close_price = latest["close"]
        
        # 1. Volatility & ATR Calculation
        atr = self.calculate_atr(candles)
        sl_distance = atr * 1.5
        tp_distance = atr * 3.0  # 1:2 Risk-to-Reward Ratio

        # 2. Basic Moving Average Confluence Logic
        closes = [c["close"] for c in candles]
        ema20 = sum(closes[-20:]) / 20
        ema50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ema20

        score = 0
        action = "HOLD"

        # Bullish Setup
        if close_price > ema20 and ema20 > ema50:
            score += 40
            # Additional candle momentum check
            if latest["close"] > latest["open"]:
                score += 35
            action = "BUY"
            sl = round(close_price - sl_distance, 4)
            tp = round(close_price + tp_distance, 4)

        # Bearish Setup
        elif close_price < ema20 and ema20 < ema50:
            score += 40
            if latest["close"] < latest["open"]:
                score += 35
            action = "SELL"
            sl = round(close_price + sl_distance, 4)
            tp = round(close_price - tp_distance, 4)

        else:
            sl, tp = 0.0, 0.0

        # Auto Lot Size Calculation
        lot_size = self.calculate_lot_size(balance, sl_distance, close_price, risk_pct=0.01)

        return {
            "symbol": symbol,
            "action": action if score >= 70 else "HOLD",
            "score": score,
            "price": close_price,
            "stop_loss": sl,
            "take_profit": tp,
            "recommended_lot": lot_size,
            "atr": round(atr, 5),
            "risk_reward_ratio": "1:2"
        }

strategy_evaluator = StrategyEvaluator()
