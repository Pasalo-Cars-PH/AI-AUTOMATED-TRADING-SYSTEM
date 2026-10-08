"""Paper-only position management helpers.

No broker execution lives here. These functions evaluate completed OHLC candles
against stored paper positions and return deterministic close decisions.
"""

def evaluate_position_on_candle(trade, candle):
    """Return a close decision for one completed candle, or None.

    Conservative rule: if SL and TP are both touched in the same candle,
    SL wins because OHLC data cannot establish intrabar ordering.
    """
    if trade.get("status") != "OPEN":
        return None

    side = str(trade.get("type", "")).upper()
    try:
        high = float(candle["high"])
        low = float(candle["low"])
        entry = float(trade["entry"])
        sl = float(trade["sl"])
        tp = float(trade["tp"])
    except (KeyError, TypeError, ValueError):
        return None

    if side == "BUY":
        sl_hit = low <= sl
        tp_hit = high >= tp
    elif side == "SELL":
        sl_hit = high >= sl
        tp_hit = low <= tp
    else:
        return None

    if sl_hit:
        return {"result": "LOSS", "exit_price": sl, "reason": "SL_HIT"}
    if tp_hit:
        return {"result": "WIN", "exit_price": tp, "reason": "TP_HIT"}
    return None


def realized_r(trade, exit_price):
    """Calculate realized R from the stored entry and SL."""
    entry = float(trade["entry"])
    sl = float(trade["sl"])
    exit_price = float(exit_price)
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    if str(trade.get("type", "")).upper() == "BUY":
        return (exit_price - entry) / risk
    if str(trade.get("type", "")).upper() == "SELL":
        return (entry - exit_price) / risk
    return None
