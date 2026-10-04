"""
Strategy 1: Liquidity sweep of PDH/PDL/Asia range + displacement + FVG limit entry + Pinbar confirmation
Defined BEFORE testing. Now with pinbar/hammer/shooting star filter.
London 07-10 UTC, NY 12-15 UTC killzones.
"""
from.base import StrategyBase
from.pinbar_detector import is_bullish_pinbar, is_bearish_pinbar, pinbar_score
import pandas as pd
import numpy as np

class StrategyLiquiditySweepFVG(StrategyBase):
    name = "strategy_1_liquidity_sweep_fvg"

    def generate_signals(self, data):
        df_m5 = data.get("M5")
        if df_m5 is None or getattr(df_m5, 'empty', True):
            df_m5 = data.get("M15")
        if df_m5 is None or getattr(df_m5, 'empty', True):
            return pd.DataFrame()

        df = df_m5.copy()
        atr_period = 14
        df['tr'] = np.maximum(df['high']-df['low'], np.maximum(abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())))
        df['atr'] = df['tr'].rolling(atr_period).mean()
        df['date'] = df['datetime'].dt.date
        daily = df.groupby('date').agg({'high':'max','low':'min'}).shift(1)
        df = df.merge(daily, left_on='date', right_index=True, suffixes=('','_prev'))
        df.rename(columns={'high_prev':'pdh','low_prev':'pdl'}, inplace=True)

        asia_start, asia_end = self.params['asia_range']
        def in_asia(dt):
            from datetime import datetime
            s = datetime.strptime(asia_start, "%H:%M").time()
            e = datetime.strptime(asia_end, "%H:%M").time()
            return s <= dt.time() <= e
        df['is_asia'] = df['datetime'].apply(in_asia)
        asia_levels = df[df['is_asia']].groupby('date').agg({'high':'max','low':'min'})
        df = df.merge(asia_levels, left_on='date', right_index=True, suffixes=('','_asia'), how='left')
        df.rename(columns={'high_asia':'asia_high','low_asia':'asia_low'}, inplace=True)

        buffer = self.params.get('sweep_buffer_pips', 2.0)
        signals = []
        killzones = self.params.get('killzones', [["07:00","10:00"],["12:00","15:00"]])
        fvg_min = self.params.get('fvg_min_size_pips', 1.0)
        sl_buf = self.params.get('sl_buffer_pips', 1.5)
        tp_r = self.params.get('tp_r', 2.0)
        disp_mult = self.params.get('displacement_atr_mult', 1.2)
        disp_look = self.params.get('displacement_lookback', 3)
        require_pinbar = self.params.get('require_pinbar', False)
        wick_mult = self.params.get('pinbar_wick_mult', 2.0)

        def pip_size(close_price):
            return 0.1 if close_price > 100 else 0.0001

        for i in range(100, len(df)-5):
            row = df.iloc[i]
            if not self.is_killzone(row['datetime'], killzones):
                continue

            ps = pip_size(row['close'])
            buf_price = buffer * ps
            sl_buf_price = sl_buf * ps
            fvg_min_price = fvg_min * ps

            levels = []
            if not pd.isna(row.get('pdh')):
                levels.append(('pdh', row['pdh'], 'short'))
            if not pd.isna(row.get('pdl')):
                levels.append(('pdl', row['pdl'], 'long'))
            if not pd.isna(row.get('asia_high')):
                levels.append(('asia_high', row['asia_high'], 'short'))
            if not pd.isna(row.get('asia_low')):
                levels.append(('asia_low', row['asia_low'], 'long'))

            for lvl_name, lvl_price, direction in levels:
                high = row['high']
                low = row['low']
                swept = False
                extreme = None
                if direction == 'short':
                    if high > lvl_price + buf_price and row['close'] < lvl_price:
                        swept = True
                        extreme = high
                else:
                    if low < lvl_price - buf_price and row['close'] > lvl_price:
                        swept = True
                        extreme = low
                if not swept:
                    continue

                disp_ok = False
                for k in range(1, disp_look+1):
                    if i+k >= len(df): break
                    nxt = df.iloc[i+k]
                    body = abs(nxt['close']-nxt['open'])
                    if body > disp_mult * row['atr']:
                        if direction == 'long' and nxt['close'] > nxt['open']:
                            disp_ok = True
                        if direction == 'short' and nxt['close'] < nxt['open']:
                            disp_ok = True
                        if disp_ok:
                            break
                if not disp_ok:
                    continue

                for j in range(i+1, min(i+10, len(df)-2)):
                    b0 = df.iloc[j]
                    b2 = df.iloc[j+2]
                    fvg = None
                    fvg_low = None
                    fvg_high = None
                    if direction == 'long':
                        if b2['low'] > b0['high'] and (b2['low']-b0['high']) >= fvg_min_price:
                            fvg = 'bull'
                            fvg_low = b0['high']
                            fvg_high = b2['low']
                    else:
                        if b0['low'] > b2['high'] and (b0['low']-b2['high']) >= fvg_min_price:
                            fvg = 'bear'
                            fvg_low = b2['high']
                            fvg_high = b0['low']

                    if fvg:
                        # PINBAR CONFIRMATION sa FVG candle
                        if require_pinbar:
                            if direction == 'long' and not is_bullish_pinbar(b2, wick_mult):
                                continue
                            if direction == 'short' and not is_bearish_pinbar(b2, wick_mult):
                                continue

                        entry_price = (fvg_low + fvg_high)/2
                        if direction == 'long':
                            sl = extreme - sl_buf_price if extreme else row['low'] - sl_buf_price
                            if sl >= entry_price:
                                sl = entry_price - 2*sl_buf_price
                            risk = entry_price - sl
                            tp = entry_price + risk * tp_r
                        else:
                            sl = extreme + sl_buf_price if extreme else row['high'] + sl_buf_price
                            if sl <= entry_price:
                                sl = entry_price + 2*sl_buf_price
                            risk = sl - entry_price
                            tp = entry_price - risk * tp_r

                        if risk <= 0:
                            continue

                        pinbar_info = pinbar_score(b2)
                        signals.append({
                            'datetime': b2['datetime'],
                            'side': direction,
                            'entry_type': 'limit',
                            'entry_price': entry_price,
                            'sl': sl,
                            'tp': tp,
                            'reason': f"{lvl_name}_sweep_disp_fvg_{fvg}_pinbar_{pinbar_info['name']}",
                            'level_price': lvl_price,
                            'atr': row['atr'],
                            'pinbar': pinbar_info['name']
                        })
                        break

        return pd.DataFrame(signals)
