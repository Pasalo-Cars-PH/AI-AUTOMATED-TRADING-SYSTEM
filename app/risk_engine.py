"""Deterministic portfolio risk controls for paper trading.

No broker execution lives here. A trade is eligible only when its monetary
risk can be calculated from supplied equity, entry, and stop-loss.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.5
    max_total_open_risk_pct: float = 3.0
    max_correlated_risk_pct: float = 1.5
    daily_loss_limit_pct: float = 2.0
    max_consecutive_losses: int = 4
    max_open_positions: int = 6
    min_rr: float = 1.5

    @classmethod
    def from_env(cls, env=None):
        import os
        env = env or os.environ
        return cls(
            risk_per_trade_pct=float(env.get("RISK_PER_TRADE_PCT", "0.5")),
            max_total_open_risk_pct=float(env.get("MAX_TOTAL_OPEN_RISK_PCT", "3.0")),
            max_correlated_risk_pct=float(env.get("MAX_CORRELATED_RISK_PCT", "1.5")),
            daily_loss_limit_pct=float(env.get("DAILY_LOSS_LIMIT_PCT", "2.0")),
            max_consecutive_losses=int(env.get("MAX_CONSECUTIVE_LOSSES", "4")),
            max_open_positions=int(env.get("MAX_OPEN_POSITIONS", "6")),
            min_rr=float(env.get("MIN_RR", "1.5")),
        )


def _positive_float(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def risk_amount_usd(equity_usd, risk_pct):
    equity = _positive_float(equity_usd, "equity_usd")
    pct = _positive_float(risk_pct, "risk_pct")
    return equity * pct / 100.0


def stop_distance(entry, sl):
    entry = _positive_float(entry, "entry")
    sl = _positive_float(sl, "sl")
    distance = abs(entry - sl)
    if distance <= 0:
        raise ValueError("entry and sl must differ")
    return distance


def position_size_units(equity_usd, risk_pct, entry, sl):
    risk_usd = risk_amount_usd(equity_usd, risk_pct)
    distance = stop_distance(entry, sl)
    return risk_usd / distance


def realized_pnl_usd(trade: Dict, exit_price: float) -> float:
    entry = _positive_float(trade.get("entry"), "entry")
    exit_price = _positive_float(exit_price, "exit_price")
    units = _positive_float(trade.get("position_size"), "position_size")
    side = str(trade.get("type", "")).upper()
    if side == "BUY":
        return (exit_price - entry) * units
    if side == "SELL":
        return (entry - exit_price) * units
    raise ValueError("trade side must be BUY or SELL")


def realized_r(trade: Dict, exit_price: float) -> float:
    pnl = realized_pnl_usd(trade, exit_price)
    risk_usd = _positive_float(trade.get("risk_usd"), "risk_usd")
    return pnl / risk_usd


def _closed_today(trades: List[Dict], now: Optional[datetime] = None):
    now = now or datetime.now(timezone.utc)
    today = now.date()
    rows = []
    for t in trades:
        if t.get("status") != "CLOSED" or t.get("r") is None:
            continue
        stamp = t.get("closed_at") or t.get("time")
        try:
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if dt.date() == today:
                rows.append(t)
        except (TypeError, ValueError):
            continue
    return rows


def consecutive_losses(trades: List[Dict]) -> int:
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("result") in ("WIN", "LOSS")]
    closed.sort(key=lambda t: str(t.get("closed_at") or t.get("time") or ""))
    count = 0
    for t in reversed(closed):
        if t.get("result") == "LOSS":
            count += 1
        else:
            break
    return count


def open_risk_usd(trades: List[Dict]) -> float:
    return sum(float(t.get("risk_usd", 0) or 0) for t in trades if t.get("status") == "OPEN")


def daily_realized_pnl_usd(trades: List[Dict], now=None) -> float:
    return sum(float(t.get("realized_pnl_usd", 0) or 0) for t in _closed_today(trades, now))


def evaluate_risk(
    trades: List[Dict],
    *,
    equity_usd,
    entry,
    sl,
    tp,
    side,
    symbol,
    config: RiskConfig,
    now=None,
):
    """Return a deterministic allow/reject decision and complete risk snapshot."""
    try:
        equity = _positive_float(equity_usd, "equity_usd")
        entry = _positive_float(entry, "entry")
        sl = _positive_float(sl, "sl")
        tp = _positive_float(tp, "tp")
    except ValueError as exc:
        return {"allow": False, "reason": str(exc)}

    side = str(side).upper()
    if side not in ("BUY", "SELL"):
        return {"allow": False, "reason": "invalid_side"}

    if (side == "BUY" and not (sl < entry < tp)) or (side == "SELL" and not (tp < entry < sl)):
        return {"allow": False, "reason": "invalid_price_structure"}

    distance = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / distance if distance else 0.0
    risk_usd = risk_amount_usd(equity, config.risk_per_trade_pct)
    units = risk_usd / distance

    opens = [t for t in trades if t.get("status") == "OPEN"]
    total_open = open_risk_usd(trades)
    total_open_pct = total_open / equity * 100.0

    same_symbol = [
        t for t in opens
        if str(t.get("symbol") or t.get("pair") or "").upper() == str(symbol).upper()
    ]
    correlated_usd = open_risk_usd(same_symbol)
    correlated_pct = (correlated_usd + risk_usd) / equity * 100.0

    daily_pnl = daily_realized_pnl_usd(trades, now)
    daily_loss_pct = max(0.0, -daily_pnl / equity * 100.0)

    checks = [
        ("risk_lock", risk_usd > 0),
        ("rr", rr >= config.min_rr),
        ("max_open_positions", len(opens) < config.max_open_positions),
        ("max_total_open_risk", total_open_pct + config.risk_per_trade_pct <= config.max_total_open_risk_pct),
        ("max_correlated_risk", correlated_pct <= config.max_correlated_risk_pct),
        ("daily_loss_limit", daily_loss_pct < config.daily_loss_limit_pct),
        ("consecutive_loss_lock", consecutive_losses(trades) < config.max_consecutive_losses),
    ]
    failed = [name for name, passed in checks if not passed]

    return {
        "allow": not failed,
        "reason": "PASS" if not failed else ",".join(failed),
        "equity_usd": round(equity, 4),
        "risk_pct": config.risk_per_trade_pct,
        "risk_usd": round(risk_usd, 4),
        "position_size": round(units, 8),
        "stop_distance": round(distance, 8),
        "rr": round(rr, 4),
        "open_positions": len(opens),
        "open_risk_usd": round(total_open, 4),
        "open_risk_pct": round(total_open_pct, 4),
        "correlated_risk_pct": round(correlated_pct, 4),
        "daily_realized_pnl_usd": round(daily_pnl, 4),
        "daily_loss_pct": round(daily_loss_pct, 4),
        "consecutive_losses": consecutive_losses(trades),
        "checks": [{"name": n, "pass": p} for n, p in checks],
        "config": {
            "risk_per_trade_pct": config.risk_per_trade_pct,
            "max_total_open_risk_pct": config.max_total_open_risk_pct,
            "max_correlated_risk_pct": config.max_correlated_risk_pct,
            "daily_loss_limit_pct": config.daily_loss_limit_pct,
            "max_consecutive_losses": config.max_consecutive_losses,
            "max_open_positions": config.max_open_positions,
            "min_rr": config.min_rr,
        },
    }
