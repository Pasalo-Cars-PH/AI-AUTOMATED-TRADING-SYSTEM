import logging
import pandas as pd
import ta

logger = logging.getLogger("trading_bot")

class StrategyEvaluator:
    def __init__(self, min_confluence_score: float = 65.0):
        self.min_confluence_score = min_confluence_score

    def evaluate(self, df_m5: pd.DataFrame, df_h1: pd.DataFrame, symbol: str) -> dict:
        if df_m5.empty or len(df_m5) < 30 or df_h1.empty or len(df_h1) < 30:
            return {"signal": "NEUTRAL", "score": 0, "reason": "Insufficient data"}

        # --- MULTI-TIMEFRAME ALIGNMENT (H1 Trend) ---
        h1_close = df_h1['close']
        h1_ema20 = ta.trend.ema_indicator(h1_close, window=20).iloc[-1]
        h1_ema50 = ta.trend.ema_indicator(h1_close, window=50).iloc[-1]
        h1_trend = "BULLISH" if h1_ema20 > h1_ema50 else "BEARISH"

        # --- M5 INDICATORS ---
        close = df_m5['close']
        high = df_m5['high']
        low = df_m5['low']

        current_rsi = ta.momentum.rsi(close, window=14).iloc[-1]
        m5_ema20 = ta.trend.ema_indicator(close, window=20).iloc[-1]
        m5_ema50 = ta.trend.ema_indicator(close, window=50).iloc[-1]

        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]

        # ATR Calculation for Dynamic TP/SL
        atr = ta.volatility.average_true_range(high, low, close, window=14).iloc[-1]
        current_price = close.iloc[-1]

        buy_score = 0
        sell_score = 0

        # Confluence Rules
        if current_rsi < 35: buy_score += 30
        elif current_rsi > 65: sell_score += 30

        if m5_ema20 > m5_ema50: buy_score += 30
        elif m5_ema20 < m5_ema50: sell_score += 30

        if current_price <= bb_lower: buy_score += 25
        elif current_price >= bb_upper: sell_score += 25

        # Trend Alignment Bonus / Penalty
        if h1_trend == "BULLISH":
            buy_score += 15
        elif h1_trend == "BEARISH":
            sell_score += 15

        # Final Signal Determination
        signal = "NEUTRAL"
        final_score = max(buy_score, sell_score)
        tp_price, sl_price = 0.0, 0.0

        if buy_score >= self.min_confluence_score and buy_score > sell_score and h1_trend == "BULLISH":
            signal = "BUY"
            sl_price = current_price - (1.5 * atr)
            tp_price = current_price + (3.0 * atr)  # 1:2 Risk/Reward
        elif sell_score >= self.min_confluence_score and sell_score > buy_score and h1_trend == "BEARISH":
            signal = "SELL"
            sl_price = current_price + (1.5 * atr)
            tp_price = current_price - (3.0 * atr)  # 1:2 Risk/Reward

        return {
            "symbol": symbol,
            "timeframe": "M5",
            "signal": signal,
            "score": final_score,
            "price": current_price,
            "tp_price": round(tp_price, 2),
            "sl_price": round(sl_price, 2),
            "h1_trend": h1_trend,
            "metrics": {
                "rsi": round(current_rsi, 2),
                "atr": round(atr, 2),
                "ema20": round(m5_ema20, 2),
                "ema50": round(m5_ema50, 2)
            }
        }

strategy_evaluator = StrategyEvaluator()
