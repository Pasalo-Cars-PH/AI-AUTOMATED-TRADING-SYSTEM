"""Translate validated closed-candle OHLCV into conservative V10 features.

Only features with implemented, deterministic calculations are emitted as PASS/FAIL.
Unsupported checkpoints are explicitly UNAVAILABLE; this adapter never fabricates them.
Bars must be chronological (oldest first), from one timeframe, and already closed.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .checkpoints import CHECKPOINTS
from .indicators import adx, ema, macd, rsi
from .structure import fair_value_gaps, liquidity_sweeps, structure_break, validate_bars


def _feature(status: str, reason: str, direction: str | None = None, **extra: Any) -> dict[str, Any]:
    result = {"status": status, "reason": reason}
    if direction in {"BUY", "SELL"}:
        result["direction"] = direction
    result.update(extra)
    return result


def build_features(
    bars: Sequence[Mapping[str, Any]],
    *,
    closed_candles_only: bool,
    timeframe: str,
    ema_fast: int = 20,
    ema_slow: int = 50,
    rsi_period: int = 14,
    adx_period: int = 14,
    sweep_lookback: int = 20,
) -> dict[str, dict[str, Any]]:
    """Build only supported checkpoint inputs from one validated OHLCV timeframe."""
    features: dict[str, dict[str, Any]] = {}
    for cp in CHECKPOINTS:
        if cp.weight:
            features[cp.feature] = _feature("UNAVAILABLE", "No verified calculator/provider wired for this checkpoint")

    if not closed_candles_only:
        return {k: _feature("UNAVAILABLE", "Open candle rejected; closed candles only") for k in features}
    if not isinstance(timeframe, str) or not timeframe.strip():
        return features

    xs = validate_bars(bars, minimum=max(ema_slow, 2 * adx_period + 1, sweep_lookback + 1, rsi_period + 1))
    closes = [x["close"] for x in xs]
    highs = [x["high"] for x in xs]
    lows = [x["low"] for x in xs]

    fast_value, slow_value = ema(closes, ema_fast), ema(closes, ema_slow)
    ema_direction = "BUY" if fast_value > slow_value else "SELL" if fast_value < slow_value else None
    features["ema_hybrid"] = (
        _feature("PASS", f"EMA{ema_fast} above EMA{ema_slow}", "BUY", fast=fast_value, slow=slow_value)
        if ema_direction == "BUY" else
        _feature("PASS", f"EMA{ema_fast} below EMA{ema_slow}", "SELL", fast=fast_value, slow=slow_value)
        if ema_direction == "SELL" else
        _feature("FAIL", "Fast and slow EMA are equal", fast=fast_value, slow=slow_value)
    )

    rsi_value = rsi(closes, rsi_period)
    rsi_direction = "BUY" if rsi_value >= 55 else "SELL" if rsi_value <= 45 else None
    features["rsi"] = (
        _feature("PASS", f"RSI {rsi_value:.2f} bullish threshold", "BUY", value=rsi_value)
        if rsi_direction == "BUY" else
        _feature("PASS", f"RSI {rsi_value:.2f} bearish threshold", "SELL", value=rsi_value)
        if rsi_direction == "SELL" else
        _feature("FAIL", f"RSI {rsi_value:.2f} inside neutral band 45-55", value=rsi_value)
    )

    macd_value = macd(closes)
    hist = macd_value["histogram"]
    macd_direction = "BUY" if hist > 0 else "SELL" if hist < 0 else None
    features["macd"] = (
        _feature("PASS", "MACD histogram positive", "BUY", **macd_value)
        if macd_direction == "BUY" else
        _feature("PASS", "MACD histogram negative", "SELL", **macd_value)
        if macd_direction == "SELL" else
        _feature("FAIL", "MACD histogram is zero", **macd_value)
    )

    adx_value = adx(highs, lows, closes, adx_period)
    strong = adx_value["adx"] >= 20.0
    features["adx"] = _feature(
        "PASS" if strong else "FAIL",
        f"ADX {adx_value['adx']:.2f} {'meets' if strong else 'below'} minimum 20",
        **adx_value,
    )

    fvg_events = fair_value_gaps(xs)
    latest_fvg = next((event for event in reversed(fvg_events) if event["index"] == len(xs) - 1), None)
    features["fvg"] = (
        _feature("PASS", "Three-candle FVG formed on latest closed candle", latest_fvg["direction"], **{k: v for k, v in latest_fvg.items() if k != "direction"})
        if latest_fvg else
        _feature("FAIL", "No three-candle FVG formed on latest closed candle")
    )

    sweep_events = liquidity_sweeps(xs, sweep_lookback)
    latest_sweep = next((event for event in reversed(sweep_events) if event["index"] == len(xs) - 1), None)
    features["liquidity_sweep"] = (
        _feature("PASS", "Liquidity sweep and close back through prior level", latest_sweep["direction"], **{k: v for k, v in latest_sweep.items() if k != "direction"})
        if latest_sweep else
        _feature("FAIL", "No liquidity sweep on latest closed candle")
    )

    bos = structure_break(xs)
    if bos.get("status") == "PASS":
        features["bos_choch"] = _feature("PASS", f"Confirmed {bos['event']}", bos["direction"], **{k: v for k, v in bos.items() if k not in {"status", "direction"}})
        # Do not count the same BOS event twice. Market structure needs its own
        # swing-sequence/trend-state calculator before it can contribute a score.
        features["market_structure"] = _feature(
            "UNAVAILABLE",
            "Distinct swing-sequence market-structure calculator not implemented; BOS is scored separately",
        )
    else:
        features["bos_choch"] = _feature(
            bos.get("status", "UNAVAILABLE"),
            bos.get("reason", "No confirmed structure break"),
            **{k: v for k, v in bos.items() if k not in {"status", "reason", "direction"}},
        )
        features["market_structure"] = _feature(
            "UNAVAILABLE",
            "Distinct swing-sequence market-structure calculator not implemented; BOS is scored separately",
        )

    return features
