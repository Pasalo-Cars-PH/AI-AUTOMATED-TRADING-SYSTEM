import logging
import pandas as pd
import ta

logger = logging.getLogger("trading_bot")

class StrategyEvaluator:
    def __init__(self, min_confluence_score: float = 65.0):
        self.min_confluence_score = min_confluence_score

    def evaluate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
        """
        Evaluates technical indicators and generates a confluence score (0-100).
        """
        if df.empty or len(df) < 30:
            return {"signal": "NEUTRAL", "score": 0, "reason": "Insufficient data"}

        # Calculate Technical Indicators using 'ta' library
        close = df['close']
        high = df['high']
        low = df['low']

        # 1. Momentum: RSI (14)
        rsi_series = ta.momentum.rsi(close, window=14)
        current_rsi = rsi_series.iloc[-1]

        # 2. Trend: EMA 20 & EMA 50
        ema20 = ta.trend.ema_indicator(close, window=20).iloc[-1]
        ema50 = ta.trend.ema_indicator(close, window=50).iloc[-1]

        # 3. Volatility: Bollinger Bands
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]

        current_price = close.iloc[-1]

        # Confluence Scoring Logic
        buy_score = 0
        sell_score = 0

        # RSI Checks
        if current_rsi < 30:
            buy_score += 35  # Oversold condition
        elif current_rsi > 70:
            sell_score += 35 # Overbought condition

        # Trend Checks (EMA Crossover / Alignment)
        if ema20 > ema50:
            buy_score += 35  # Bullish trend
        elif ema20 < ema50:
            sell_score += 35 # Bearish trend

        # Bollinger Band Breakout/Bounce
        if current_price <= bb_lower:
            buy_score += 30  # Bounce off lower band
        elif current_price >= bb_upper:
            sell_score += 30 # Rejection off upper band

        # Determine Final Signal & Score
        if buy_score >= self.min_confluence_score and buy_score > sell_score:
            signal = "BUY"
            final_score = buy_score
        elif sell_score >= self.min_confluence_score and sell_score > buy_score:
            signal = "SELL"
            final_score = sell_score
        else:
            signal = "NEUTRAL"
            final_score = max(buy_score, sell_score)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": signal,
            "score": final_score,
            "price": current_price,
            "metrics": {
                "rsi": round(current_rsi, 2),
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2),
                "bb_upper": round(bb_upper, 2),
                "bb_lower": round(bb_lower, 2)
            }
        }

strategy_evaluator = StrategyEvaluator()
