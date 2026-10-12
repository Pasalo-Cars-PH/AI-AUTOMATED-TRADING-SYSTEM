import math

from app.main import _atr_series, calculate_ema, calculate_rsi, calculate_supertrend


def candles(n=120):
    # Deterministic indicator fixture only; never used as market input or a trade signal.
    closes = [2000.0 + i * 0.15 + math.sin(i / 4.0) * 0.8 for i in range(n)]
    highs = [c + 0.7 for c in closes]
    lows = [c - 0.6 for c in closes]
    return closes, highs, lows


def test_ema_is_computed_from_oldest_to_newest_closed_values():
    closes, _, _ = candles()
    value = calculate_ema(closes, 20)
    assert value is not None
    assert math.isfinite(value)
    assert value > 0


def test_rsi_is_finite_and_in_range_for_valid_series():
    closes, _, _ = candles()
    value = calculate_rsi(closes, 14)
    assert value is not None
    assert math.isfinite(value)
    assert 0 <= value <= 100


def test_atr_and_supertrend_are_available_with_sufficient_valid_bars():
    closes, highs, lows = candles()
    atr = _atr_series(highs, lows, closes, 14)[-1]
    st = calculate_supertrend(highs, lows, closes, period=10, multiplier=3.0)
    assert atr is not None and math.isfinite(atr) and atr > 0
    assert st is not None
    assert math.isfinite(st["supertrend"])
    assert st["trend"] in {"BULL", "BEAR"}


def test_indicators_fail_closed_when_history_is_too_short():
    closes = [2000.0, 2001.0, 2002.0]
    assert calculate_ema(closes, 20) is None
    assert _atr_series(closes, closes, closes, 14)[-1] is None
    assert calculate_supertrend(closes, closes, closes, period=10, multiplier=3.0) is None
