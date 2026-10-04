from.base import StrategyBase
from.pinbar_detector import is_bullish_pinbar, is_bearish_pinbar, pinbar_score
import pandas as pd
import numpy as np

class StrategyTrendPullback(StrategyBase):
    name = "strategy_2_trend_pullback"
    def _ema(self, s, period):
        return s.ewm(span=period, adjust=False).mean()

    def generate_signals(self, data):
        df_m15 = data.get("M15")
        df_h1 = data.get("H1")
        if df_m15 is None or getattr(df_m15, 'empty', True):
            return pd.DataFrame()
        if df_h1 is None or getattr(df_h1, 'empty', True):
            df_h1 = df_m15.copy()

        df_h1 = df_h1.copy()
        df_h1['ema_fast'] = self._ema(df_h1['close'], self.params.get('ema_fast', 50))
        df_h1['ema_slow'] = self._ema(df_h1['close'], self.params.get('ema_slow', 200))
        df_h1['trend'] = np.where(df_h1['ema_fast'] > df_h1['ema_slow'], 1, -1)

        df = df_m15.copy()
        df['ema_pullback'] = self._ema(df['close'], self.params.get('pullback_ema', 21))
        df['tr'] = np.maximum(df['high']-df['low'], np.maximum(abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())))
        df['atr'] = df['tr'].rolling(self.params.get('atr_period',14)).mean()
        if self.params.get('rsi_filter'):
            delta = df['close'].diff()
            gain = delta.clip(lower=0).rolling(self.params.get('rsi_period',14)).mean()
            loss = (-delta.clip(upper=0)).rolling(self.params.get('rsi_period',14)).mean()
            df['rsi'] = 100 - (100/(1+gain/loss))

        df_h1_indexed = df_h1.set_index('datetime')[['trend']]
        df = df.set_index('datetime')
        df = df.merge(df_h1_indexed, left_index=True, right_index=True, how='left')
        df['trend'] = df['trend'].ffill()
        df = df.reset_index()

        signals = []
        atr_mult = self.params.get('atr_sl_mult', 1.5)
        tp_r = self.params.get('tp_r', 1.8)
        require_pinbar = self.params.get('require_pinbar', False)
        wick_mult = self.params.get('pinbar_wick_mult', 2.0)

        for i in range(200, len(df)-2):
            row = df.iloc[i]
            if pd.isna(row.get('trend')) or pd.isna(row.get('atr')):
                continue
            trend = row['trend']
            dist = abs(row['close'] - row['ema_pullback'])
            if dist > 0.5 * row['atr']:
                continue
            if self.params.get('rsi_filter') and 'rsi' in df.columns:
                rsi = row.get('rsi')
                if pd.isna(rsi):
                    continue
                if trend == 1 and rsi < self.params.get('rsi_long_min',40):
                    continue
                if trend == -1 and rsi > self.params.get('rsi_short_max',60):
                    continue

            prev = df.iloc[i-1]
            two_ago = df.iloc[i-2]
            hl_long = row['low'] > two_ago['low'] and prev['low'] > two_ago['low']
            hl_short = row['high'] < two_ago['high'] and prev['high'] < two_ago['high']

            bullish_pin = is_bullish_pinbar(row, wick_mult)
            bearish_pin = is_bearish_pinbar(row, wick_mult)

            if require_pinbar:
                if trend == 1 and not bullish_pin:
                    continue
                if trend == -1 and not bearish_pin:
                    continue

            side = None
            if trend == 1 and hl_long and row['close'] > row['open'] and row['close'] > row['ema_pullback']:
                if bullish_pin or not require_pinbar:
                    side = 'long'
            elif trend == -1 and hl_short and row['close'] < row['open'] and row['close'] < row['ema_pullback']:
                if bearish_pin or not require_pinbar:
                    side = 'short'

            if side is None:
                continue

            entry = row['close']
            atr = row['atr']
            if side == 'long':
                sl = entry - atr * atr_mult
                risk = entry - sl
                tp = entry + risk * tp_r
            else:
                sl = entry + atr * atr_mult
                risk = sl - entry
                tp = entry - risk * tp_r

            if risk <= 0:
                continue

            pinbar_type = 'Hammer' if bullish_pin else ('ShootingStar' if bearish_pin else 'none')
            signals.append({
                'datetime': row['datetime'],
                'side': side,
                'entry_type': 'market',
                'entry_price': entry,
                'sl': sl,
                'tp': tp,
                'reason': f"trend_pullback_H1_{'up' if trend==1 else 'down'}_HL_{pinbar_type}",
                'atr': atr,
                'trend': trend,
                'pinbar': pinbar_type
            })

        return pd.DataFrame(signals)
