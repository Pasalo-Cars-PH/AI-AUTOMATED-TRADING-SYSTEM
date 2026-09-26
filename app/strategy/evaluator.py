import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("trading_bot")

class Institutional10LayerEvaluator:
    def __init__(self):
        self.min_confluence_score = 8  # Kailangan ng at least 8/10 layers

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # Exponential Moving Averages (EMA)
        df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

        # Relative Strength Index (RSI)
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

        # Average True Range (ATR)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(14).mean()

        # Volume Moving Average
        df['vol_ma'] = df['volume'].rolling(20).mean()

        return df

    def evaluate_signal(self, df_m5: pd.DataFrame, df_h1: pd.DataFrame = None) -> dict:
        if len(df_m5) < 200:
            return {"signal": "NEUTRAL", "reason": "Insufficient candles for 10-layer analysis"}

        df = self.calculate_indicators(df_m5)
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        score_buy = 0
        score_sell = 0
        reasons_buy = []
        reasons_sell = []

        # Layer 1: H1 Trend Alignment (kung available ang H1)
        if df_h1 is not None and len(df_h1) >= 50:
            df_h1_calc = self.calculate_indicators(df_h1)
            h1_curr = df_h1_calc.iloc[-1]
            if h1_curr['close'] > h1_curr['ema_50']:
                score_buy += 1
                reasons_buy.append("L1: H1 Trend Bullish")
            elif h1_curr['close'] < h1_curr['ema_50']:
                score_sell += 1
                reasons_sell.append("L1: H1 Trend Bearish")
        else:
            # Fallback sa M5 EMA 200
            if curr['close'] > curr['ema_200']:
                score_buy += 1
                reasons_buy.append("L1: Above M5 EMA 200")
            else:
                score_sell += 1
                reasons_sell.append("L1: Below M5 EMA 200")

        # Layer 2: M5 EMA Triple Cross Alignment
        if curr['ema_9'] > curr['ema_21'] > curr['ema_50']:
            score_buy += 1
            reasons_buy.append("L2: EMA Triple Bullish Cross")
        elif curr['ema_9'] < curr['ema_21'] < curr['ema_50']:
            score_sell += 1
            reasons_sell.append("L2: EMA Triple Bearish Cross")

        # Layer 3: RSI Confirmation
        if 45 <= curr['rsi'] <= 68:
            score_buy += 1
            reasons_buy.append("L3: RSI Bullish Zone")
        elif 32 <= curr['rsi'] <= 55:
            score_sell += 1
            reasons_sell.append("L3: RSI Bearish Zone")

        # Layer 4: MACD Histogram Acceleration
        if curr['macd'] > curr['macd_signal'] and curr['macd_hist'] > prev['macd_hist']:
            score_buy += 1
            reasons_buy.append("L4: MACD Bullish Acceleration")
        elif curr['macd'] < curr['macd_signal'] and curr['macd_hist'] < prev['macd_hist']:
            score_sell += 1
            reasons_sell.append("L4: MACD Bearish Acceleration")

        # Layer 5: Bollinger Bands Breakout/Rebound
        if curr['close'] > curr['bb_middle'] and prev['close'] <= prev['bb_middle']:
            score_buy += 1
            reasons_buy.append("L5: BB Middle Band Bullish Cross")
        elif curr['close'] < curr['bb_middle'] and prev['close'] >= prev['bb_middle']:
            score_sell += 1
            reasons_sell.append("L5: BB Middle Band Bearish Cross")

        # Layer 6: Institutional Volume Confirmation
        if curr['volume'] > (1.3 * curr['vol_ma']):
            score_buy += 1
            score_sell += 1
            reasons_buy.append("L6: High Institutional Volume")
            reasons_sell.append("L6: High Institutional Volume")

        # Layer 7: ATR Market Volatility Health Check
        if curr['atr'] > (0.5 * df['atr'].mean()):
            score_buy += 1
            score_sell += 1
            reasons_buy.append("L7: Healthy Market Volatility")
            reasons_sell.append("L7: Healthy Market Volatility")

        # Layer 8: Dynamic Risk-Reward (ATR Stop-Loss & Take-Profit Calc)
        atr_val = curr['atr']
        sl_distance = 1.5 * atr_val
        tp_distance = 3.0 * atr_val  # 1:2 RRR

        score_buy += 1
        score_sell += 1
        reasons_buy.append("L8: 1:2 RRR Dynamic ATR Set")
        reasons_sell.append("L8: 1:2 RRR Dynamic ATR Set")

        # Layer 9: Key Support/Resistance Distance
        recent_high = df['high'].iloc[-20:].max()
        recent_low = df['low'].iloc[-20:].min()
        
        if (recent_high - curr['close']) > sl_distance:
            score_buy += 1
            reasons_buy.append("L9: Safe Room to Resistance")
        if (curr['close'] - recent_low) > sl_distance:
            score_sell += 1
            reasons_sell.append("L9: Safe Room to Support")

        # Layer 10: Price Action Candle Pattern Filter
        is_bullish_engulfing = (curr['close'] > prev['open']) and (prev['close'] < prev['open'])
        is_bearish_engulfing = (curr['close'] < prev['open']) and (prev['close'] > prev['open'])

        if is_bullish_engulfing or (curr['close'] > curr['open']):
            score_buy += 1
            reasons_buy.append("L10: Bullish Candle Confirmation")
        elif is_bearish_engulfing or (curr['close'] < curr['open']):
            score_sell += 1
            reasons_sell.append("L10: Bearish Candle Confirmation")

        # Final Confluence Decision
        if score_buy >= self.min_confluence_score:
            return {
                "signal": "BUY",
                "score": f"{score_buy}/10",
                "price": curr['close'],
                "stop_loss": round(curr['close'] - sl_distance, 5),
                "take_profit": round(curr['close'] + tp_distance, 5),
                "reasons": reasons_buy
            }
        elif score_sell >= self.min_confluence_score:
            return {
                "signal": "SELL",
                "score": f"{score_sell}/10",
                "price": curr['close'],
                "stop_loss": round(curr['close'] + sl_distance, 5),
                "take_profit": round(curr['close'] - tp_distance, 5),
                "reasons": reasons_sell
            }

        return {
            "signal": "NEUTRAL",
            "score_buy": score_buy,
            "score_sell": score_sell,
            "reason": "Confluence score below 8/10 threshold (Filter active)"
        }
