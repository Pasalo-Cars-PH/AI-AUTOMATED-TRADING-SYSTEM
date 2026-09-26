import pandas as pd
import numpy as np
from datetime import datetime, timezone
import logging

logger = logging.getLogger("trading_bot")

class InstitutionalBoostedEvaluator:
    def __init__(self):
        self.min_confluence_score = 8

    def _is_kill_zone(self) -> bool:
        """Booster: Session Kill Zone Filter (London & New York Sessions)"""
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        # London Session: 07:00 - 16:00 UTC (3:00 PM - 12:00 AM PH Time)
        # New York Session: 12:00 - 21:00 UTC (8:00 PM - 5:00 AM PH Time)
        is_london = 7 <= hour < 16
        is_ny = 12 <= hour < 21
        return is_london or is_ny

    def _detect_fvg_and_ob(self, df: pd.DataFrame) -> dict:
        """Booster: Fair Value Gap (FVG) and Order Block (OB) Detection"""
        if len(df) < 5:
            return {"fvg": "NONE", "ob": "NONE"}
        
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        
        # Bullish FVG (Gap sa pagitan ng Candle 1 High at Candle 3 Low)
        bullish_fvg = c3['low'] > c1['high']
        # Bearish FVG (Gap sa pagitan ng Candle 1 Low at Candle 3 High)
        bearish_fvg = c3['high'] < c1['low']

        # Order Block (Huling red candle bago ang malakas na green push, o vice versa)
        is_bullish_ob = (c1['close'] < c1['open']) and (c2['close'] > c2['open']) and (c3['close'] > c2['high'])
        is_bearish_ob = (c1['close'] > c1['open']) and (c2['close'] < c2['open']) and (c3['close'] < c2['low'])

        fvg_type = "BULLISH" if bullish_fvg else ("BEARISH" if bearish_fvg else "NONE")
        ob_type = "BULLISH" if is_bullish_ob else ("BEARISH" if is_bearish_ob else "NONE")

        return {"fvg": fvg_type, "ob": ob_type}

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # EMAs
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)

        # ATR & Volume MA
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        true_range = np.max(pd.concat([high_low, high_close, low_close], axis=1), axis=1)
        df['atr'] = true_range.rolling(14).mean()
        df['vol_ma'] = df['volume'].rolling(20).mean()

        return df

    def evaluate_signal(self, df_m5: pd.DataFrame, df_h1: pd.DataFrame = None) -> dict:
        # Booster: Kill Zone Check
        if not self._is_kill_zone():
            return {"signal": "NEUTRAL", "reason": "Outside Session Kill Zones (Low Volume Avoidance)"}

        if len(df_m5) < 200:
            return {"signal": "NEUTRAL", "reason": "Insufficient candles for full analysis"}

        df = self.calculate_indicators(df_m5)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        smc = self._detect_fvg_and_ob(df)

        score_buy = 0
        score_sell = 0
        reasons_buy = []
        reasons_sell = []

        # Layer 1: Trend Alignment (H1 or M5 EMA 200)
        if df_h1 is not None and len(df_h1) >= 50:
            df_h1_calc = self.calculate_indicators(df_h1)
            h1_curr = df_h1_calc.iloc[-1]
            if h1_curr['close'] > h1_curr['ema_50']:
                score_buy += 1; reasons_buy.append("L1: H1 Trend Bullish")
            elif h1_curr['close'] < h1_curr['ema_50']:
                score_sell += 1; reasons_sell.append("L1: H1 Trend Bearish")
        else:
            if curr['close'] > curr['ema_200']:
                score_buy += 1; reasons_buy.append("L1: Above M5 EMA 200")
            else:
                score_sell += 1; reasons_sell.append("L1: Below M5 EMA 200")

        # Layer 2: M5 EMA Triple Cross
        if curr['ema_9'] > curr['ema_21'] > curr['ema_50']:
            score_buy += 1; reasons_buy.append("L2: Triple EMA Bullish Alignment")
        elif curr['ema_9'] < curr['ema_21'] < curr['ema_50']:
            score_sell += 1; reasons_sell.append("L2: Triple EMA Bearish Alignment")

        # Layer 3: RSI Momentum Zone
        if 45 <= curr['rsi'] <= 68:
            score_buy += 1; reasons_buy.append("L3: RSI Bullish Zone")
        elif 32 <= curr['rsi'] <= 55:
            score_sell += 1; reasons_sell.append("L3: RSI Bearish Zone")

        # Layer 4: MACD Acceleration
        if curr['macd'] > curr['macd_signal'] and curr['macd_hist'] > prev['macd_hist']:
            score_buy += 1; reasons_buy.append("L4: MACD Bullish Acceleration")
        elif curr['macd'] < curr['macd_signal'] and curr['macd_hist'] < prev['macd_hist']:
            score_sell += 1; reasons_sell.append("L4: MACD Bearish Acceleration")

        # Layer 5: BB Middle Rebound
        if curr['close'] > curr['bb_middle'] and prev['close'] <= prev['bb_middle']:
            score_buy += 1; reasons_buy.append("L5: BB Middle Cross Up")
        elif curr['close'] < curr['bb_middle'] and prev['close'] >= prev['bb_middle']:
            score_sell += 1; reasons_sell.append("L5: BB Middle Cross Down")

        # Layer 6: Institutional Volume Spike
        if curr['volume'] > (1.2 * curr['vol_ma']):
            score_buy += 1; score_sell += 1
            reasons_buy.append("L6: Institutional Volume Spike")
            reasons_sell.append("L6: Institutional Volume Spike")

        # Layer 7: ATR Health Check
        if curr['atr'] > (0.5 * df['atr'].mean()):
            score_buy += 1; score_sell += 1
            reasons_buy.append("L7: Healthy Market Volatility")
            reasons_sell.append("L7: Healthy Market Volatility")

        # Layer 8: SMC Fair Value Gap (FVG) Booster
        if smc['fvg'] == "BULLISH":
            score_buy += 1; reasons_buy.append("L8 (Booster): Bullish Fair Value Gap (FVG)")
        elif smc['fvg'] == "BEARISH":
            score_sell += 1; reasons_sell.append("L8 (Booster): Bearish Fair Value Gap (FVG)")

        # Layer 9: SMC Order Block (OB) Booster
        if smc['ob'] == "BULLISH":
            score_buy += 1; reasons_buy.append("L9 (Booster): Bullish Order Block Confirmed")
        elif smc['ob'] == "BEARISH":
            score_sell += 1; reasons_sell.append("L9 (Booster): Bearish Order Block Confirmed")

        # Layer 10: Candle Action & Dynamic Risk-Reward (ATR-based 1:2 RRR)
        atr_val = curr['atr']
        sl_dist = 1.5 * atr_val
        tp_dist = 3.0 * atr_val

        if curr['close'] > curr['open']:
            score_buy += 1; reasons_buy.append("L10: Bullish Candle + 1:2 ATR RRR")
        elif curr['close'] < curr['open']:
            score_sell += 1; reasons_sell.append("L10: Bearish Candle + 1:2 ATR RRR")

        # Final Approval
        if score_buy >= self.min_confluence_score:
            return {
                "signal": "BUY",
                "score": f"{score_buy}/10",
                "price": curr['close'],
                "stop_loss": round(curr['close'] - sl_dist, 5),
                "take_profit": round(curr['close'] + tp_dist, 5),
                "reasons": reasons_buy
            }
        elif score_sell >= self.min_confluence_score:
            return {
                "signal": "SELL",
                "score": f"{score_sell}/10",
                "price": curr['close'],
                "stop_loss": round(curr['close'] + sl_dist, 5),
                "take_profit": round(curr['close'] - tp_dist, 5),
                "reasons": reasons_sell
            }

        return {
            "signal": "NEUTRAL",
            "score_buy": score_buy,
            "score_sell": score_sell,
            "reason": "Score below 8/10 threshold"
        }

# Aliases para maiwasan ang anumang import mismatch errors
strategy_evaluator = InstitutionalBoostedEvaluator()
