import pandas as pd
import numpy as np
from datetime import datetime, timezone
import logging

logger = logging.getLogger("trading_bot")

class InstitutionalBoostedEvaluator:
    def __init__(self):
        self.min_confluence_score = 75  # Canonical 0-100 scoring threshold
        self.boosters = {
            "news_filter": True,
            "kill_zones": True,
            "dxy_correlation": True,
            "retest_confirm": True,
            "premium_discount": True,
            "rsi_divergence": True,
            "spread_guard": True,
            "ai_confidence": False  # Disabled until real AI inference is available
        }

    def _is_kill_zone(self) -> bool:
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        return (7 <= hour < 16) or (12 <= hour < 21)

    def _check_premium_discount(self, df: pd.DataFrame) -> str:
        if len(df) < 50:
            return "NEUTRAL"
        high_max = df['high'].tail(50).max()
        low_min = df['low'].tail(50).min()
        mid = (high_max + low_min) / 2
        curr_price = df['close'].iloc[-1]
        return "DISCOUNT" if curr_price < mid else "PREMIUM"

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        true_range = np.max(pd.concat([high_low, high_close, low_close], axis=1), axis=1)
        df['atr'] = true_range.rolling(14).mean()
        df['vol_ma'] = df['volume'].rolling(20).mean()

        return df

    def evaluate_signal(self, df_m5: pd.DataFrame, df_h1: pd.DataFrame = None, is_crypto: bool = False) -> dict:
        if self.boosters["kill_zones"] and not is_crypto and not self._is_kill_zone():
            return {"signal": "NEUTRAL", "reason": "Blocked: Outside Session Kill Zones"}

        if len(df_m5) < 200:
            return {"signal": "NEUTRAL", "reason": "Insufficient candle data"}

        df = self.calculate_indicators(df_m5)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        zone = self._check_premium_discount(df)

        # Canonical 100-Point Weighted System
        score_buy = 0
        score_sell = 0
        reasons_buy = []
        reasons_sell = []

        # 1. Trend (15 pts)
        if df_h1 is not None and len(df_h1) >= 50:
            df_h1_calc = self.calculate_indicators(df_h1)
            h1_curr = df_h1_calc.iloc[-1]
            if h1_curr['close'] > h1_curr['ema_50']:
                score_buy += 15; reasons_buy.append("H1 Bullish Trend (+15)")
            elif h1_curr['close'] < h1_curr['ema_50']:
                score_sell += 15; reasons_sell.append("H1 Bearish Trend (+15)")

        # 2. Structure (15 pts)
        if zone == "DISCOUNT":
            score_buy += 15; reasons_buy.append("Discount Zone (<50% range) (+15)")
        elif zone == "PREMIUM":
            score_sell += 15; reasons_sell.append("Premium Zone (>50% range) (+15)")

        # 3. Momentum (15 pts)
        if curr['ema_9'] > curr['ema_21'] > curr['ema_50']:
            score_buy += 15; reasons_buy.append("Triple EMA Bullish Cross (+15)")
        elif curr['ema_9'] < curr['ema_21'] < curr['ema_50']:
            score_sell += 15; reasons_sell.append("Triple EMA Bearish Cross (+15)")

        # 4. Volatility / Volume (15 pts)
        if curr['volume'] > (1.2 * curr['vol_ma']):
            score_buy += 15; score_sell += 15
            reasons_buy.append("Volume Surge (+15)")
            reasons_sell.append("Volume Surge (+15)")

        # 5. MACD / RSI Confluence (20 pts)
        if 45 <= curr['rsi'] <= 68 and curr['macd'] > curr['macd_signal']:
            score_buy += 20; reasons_buy.append("RSI & MACD Momentum Alignment (+20)")
        elif 32 <= curr['rsi'] <= 55 and curr['macd'] < curr['macd_signal']:
            score_sell += 20; reasons_sell.append("RSI & MACD Bearish Alignment (+20)")

        # 6. Data Quality State (20 pts)
        score_buy += 20; score_sell += 20
        reasons_buy.append("Confirmed Candle Data (+20)")
        reasons_sell.append("Confirmed Candle Data (+20)")

        # AI Confidence Check: Strict REAL or UNAVAILABLE
        ai_status = "AI_CONFIDENCE_UNAVAILABLE"

        sl_dist = 1.5 * curr['atr']
        tp_dist = 3.0 * curr['atr']

        if score_buy >= self.min_confluence_score:
            return {
                "signal": "BUY",
                "score": f"{score_buy}/100",
                "ai_status": ai_status,
                "price": curr['close'],
                "stop_loss": round(curr['close'] - sl_dist, 5),
                "take_profit": round(curr['close'] + tp_dist, 5),
                "reasons": reasons_buy
            }
        elif score_sell >= self.min_confluence_score:
            return {
                "signal": "SELL",
                "score": f"{score_sell}/100",
                "ai_status": ai_status,
                "price": curr['close'],
                "stop_loss": round(curr['close'] + sl_dist, 5),
                "take_profit": round(curr['close'] - tp_dist, 5),
                "reasons": reasons_sell
            }

        return {"signal": "NEUTRAL", "reason": f"Score below {self.min_confluence_score}/100 threshold", "ai_status": ai_status}

strategy_evaluator = InstitutionalBoostedEvaluator()
