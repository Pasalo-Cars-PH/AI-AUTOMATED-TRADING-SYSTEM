"""
Pinbar / Hammer / Shooting Star detector
Bullish Hammer = signal akyat, Bearish Shooting Star = signal baba
"""
import pandas as pd

def is_bullish_pinbar(row, wick_mult=2.0, body_max_pct=0.4):
    o = row['open']
    h = row['high']
    l = row['low']
    c = row['close']
    body = abs(c - o)
    range_ = h - l
    if range_ == 0:
        return False
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    if lower_wick < wick_mult * max(body, range_*0.05):
        return False
    if upper_wick > body * 1.5:
        return False
    if body > range_ * body_max_pct:
        return False
    return True

def is_bearish_pinbar(row, wick_mult=2.0, body_max_pct=0.4):
    o = row['open']
    h = row['high']
    l = row['low']
    c = row['close']
    body = abs(c - o)
    range_ = h - l
    if range_ == 0:
        return False
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    if upper_wick < wick_mult * max(body, range_*0.05):
        return False
    if lower_wick > body * 1.5:
        return False
    if body > range_ * body_max_pct:
        return False
    return True

def pinbar_score(row):
    if is_bullish_pinbar(row):
        lower_wick = min(row['open'], row['close']) - row['low']
        range_ = row['high']-row['low']
        strength = min(lower_wick / max(range_, 1e-6), 1.0)
        return {'type': 'bullish', 'score': 1, 'strength': strength, 'name': 'Hammer'}
    if is_bearish_pinbar(row):
        upper_wick = row['high'] - max(row['open'], row['close'])
        range_ = row['high']-row['low']
        strength = min(upper_wick / max(range_, 1e-6), 1.0)
        return {'type': 'bearish', 'score': -1, 'strength': strength, 'name': 'Shooting Star'}
    return {'type': 'none', 'score': 0, 'strength': 0, 'name': 'none'}
