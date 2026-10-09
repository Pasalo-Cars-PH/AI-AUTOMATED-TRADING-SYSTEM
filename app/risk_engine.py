"""Deterministic portfolio risk controls for paper trading.

No broker execution lives here. A trade is eligible only when its monetary
risk can be calculated from supplied equity, entry, and stop-loss.
"""
from dataclasses import dataclass
import json
import math
import os
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

    def __post_init__(self):
        pct_fields = (
            ("risk_per_trade_pct", self.risk_per_trade_pct),
            ("max_total_open_risk_pct", self.max_total_open_risk_pct),
            ("max_correlated_risk_pct", self.max_correlated_risk_pct),
            ("daily_loss_limit_pct", self.daily_loss_limit_pct),
        )
        for name, value in pct_fields:
            if not math.isfinite(float(value)) or not 0 < float(value) <= 100:
                raise ValueError(f"{name} must be finite and in (0, 100]")
        if self.risk_per_trade_pct > self.max_total_open_risk_pct:
            raise ValueError("risk_per_trade_pct cannot exceed max_total_open_risk_pct")
        if not math.isfinite(float(self.min_rr)) or self.min_rr <= 0:
            raise ValueError("min_rr must be finite and > 0")
        if int(self.max_consecutive_losses) < 1 or int(self.max_open_positions) < 1:
            raise ValueError("loss and position limits must be >= 1")

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


@dataclass(frozen=True)
class InstrumentSpec:
    """Verified contract metadata; size is expressed in lots/contracts."""
    contract_size: float
    quote_to_usd: float
    size_step: float

    @classmethod
    def from_mapping(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError("instrument_spec must be an object")
        return cls(
            contract_size=_positive_float(raw.get("contract_size"), "contract_size"),
            quote_to_usd=_positive_float(raw.get("quote_to_usd"), "quote_to_usd"),
            size_step=_positive_float(raw.get("size_step"), "size_step"),
        )


def instrument_spec_from_env(symbol, env=None):
    env = os.environ if env is None else env
    raw = env.get("INSTRUMENT_SPECS_JSON", "")
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(mapping, dict):
        return None
    key = str(symbol).strip().upper()
    spec = mapping.get(key)
    if spec is None:
        compact = key.replace("/", "").replace("-", "")
        spec = next((v for k, v in mapping.items()
                     if str(k).strip().upper().replace("/", "").replace("-", "") == compact), None)
    try:
        return InstrumentSpec.from_mapping(spec) if spec is not None else None
    except ValueError:
        return None


def _positive_float(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")
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


def position_size_units(equity_usd, risk_pct, entry, sl, instrument_spec):
    """Size in lots/contracts; requires explicit contract and quote conversion."""
    risk_usd = risk_amount_usd(equity_usd, risk_pct)
    distance = stop_distance(entry, sl)
    spec = instrument_spec if isinstance(instrument_spec, InstrumentSpec) else InstrumentSpec.from_mapping(instrument_spec)
    raw_size = risk_usd / (distance * spec.contract_size * spec.quote_to_usd)
    # Round DOWN to the instrument's declared tradable size increment.
    steps = math.floor((raw_size + 1e-12) / spec.size_step)
    return round(steps * spec.size_step, 10)


def realized_pnl_usd(trade: Dict, exit_price: float) -> float:
    entry = _positive_float(trade.get("entry"), "entry")
    exit_price = _positive_float(exit_price, "exit_price")
    units = _positive_float(trade.get("position_size"), "position_size")
    contract_size = _positive_float(trade.get("contract_size"), "contract_size")
    quote_to_usd = _positive_float(trade.get("quote_to_usd"), "quote_to_usd")
    side = str(trade.get("type", "")).upper()
    if side == "BUY":
        return (exit_price - entry) * units * contract_size * quote_to_usd
    if side == "SELL":
        return (entry - exit_price) * units * contract_size * quote_to_usd
    raise ValueError("trade side must be BUY or SELL")


def realized_r(trade: Dict, exit_price: float) -> float:
    pnl = realized_pnl_usd(trade, exit_price)
    risk_usd = _positive_float(trade.get("risk_usd"), "risk_usd")
    return pnl / risk_usd


def _parse_timestamp(value):
    """Parse a timestamp and normalize it to UTC. Naive stored timestamps are treated as UTC."""
    if not value:
        raise ValueError("missing_trade_timestamp")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _closed_today(trades: List[Dict], now: Optional[datetime] = None):
    now_utc = _parse_timestamp((now or datetime.now(timezone.utc)).isoformat())
    today_utc = now_utc.date()
    rows = []
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        stamp = t.get("closed_at") or t.get("time")
        try:
            if _parse_timestamp(stamp).date() == today_utc:
                rows.append(t)
        except (TypeError, ValueError):
            # Unknown close time must not silently disappear from daily risk accounting.
            raise ValueError("closed_trade_missing_or_invalid_timestamp")
    return rows


def _finite_number(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}_missing_or_invalid")
    if not math.isfinite(number):
        raise ValueError(f"{name}_missing_or_invalid")
    return number


def consecutive_losses(trades: List[Dict]) -> int:
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    for t in closed:
        # Result labels and R-multiples are not authoritative; actual realized PnL is.
        _finite_number(t.get("realized_pnl_usd"), "closed_trade_realized_pnl")
        _parse_timestamp(t.get("closed_at") or t.get("time"))
    closed.sort(key=lambda t: _parse_timestamp(t.get("closed_at") or t.get("time")))
    count = 0
    for t in reversed(closed):
        pnl = _finite_number(t.get("realized_pnl_usd"), "closed_trade_realized_pnl")
        if pnl < 0:
            count += 1
        elif pnl > 0:
            break
        else:
            # Explicit policy: breakeven resets the consecutive-loss streak.
            break
    return count


def open_risk_usd(trades: List[Dict]) -> float:
    total = 0.0
    for t in trades:
        if t.get("status") != "OPEN":
            continue
        risk = _finite_number(t.get("risk_usd"), "open_trade_risk_usd")
        if risk <= 0:
            raise ValueError("open_trade_risk_usd_missing_or_nonpositive")
        total += risk
    return total


def daily_realized_pnl_usd(trades: List[Dict], now=None) -> float:
    rows = _closed_today(trades, now)
    pnl_values = [_finite_number(t.get("realized_pnl_usd"), "closed_trade_realized_pnl") for t in rows]
    return sum(pnl_values)


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
    instrument_spec=None,
    now=None,
):
    """Return a deterministic allow/reject decision and complete risk snapshot.

    Missing contract metadata is a hard rejection; never infer a lot size.
    """
    if instrument_spec is None:
        instrument_spec = instrument_spec_from_env(symbol)
    try:
        spec = instrument_spec if isinstance(instrument_spec, InstrumentSpec) else InstrumentSpec.from_mapping(instrument_spec)
    except (ValueError, TypeError):
        return {"allow": False, "reason": "missing_or_invalid_instrument_spec"}
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
    units = position_size_units(equity, config.risk_per_trade_pct, entry, sl, spec)
    if units <= 0:
        return {"allow": False, "reason": "position_size_below_minimum_step"}
    # Monetary stop risk is computed from the rounded-down tradable size.
    risk_usd = units * distance * spec.contract_size * spec.quote_to_usd

    opens = [t for t in trades if t.get("status") == "OPEN"]
    try:
        total_open = open_risk_usd(trades)
        total_open_pct = total_open / equity * 100.0
        correlated_usd = open_risk_usd([
            t for t in opens
            if str(t.get("symbol") or t.get("pair") or "").upper() == str(symbol).upper()
        ])
        daily_pnl = daily_realized_pnl_usd(trades, now)
        loss_streak = consecutive_losses(trades)
    except ValueError as exc:
        return {"allow": False, "reason": f"portfolio_data_integrity:{exc}"}

    same_symbol = [
        t for t in opens
        if str(t.get("symbol") or t.get("pair") or "").upper() == str(symbol).upper()
    ]
    correlated_pct = (correlated_usd + risk_usd) / equity * 100.0
    daily_loss_pct = max(0.0, -daily_pnl / equity * 100.0)
    actual_risk_pct = risk_usd / equity * 100.0

    checks = [
        ("risk_lock", risk_usd > 0),
        ("rr", rr >= config.min_rr),
        ("max_open_positions", len(opens) < config.max_open_positions),
        ("max_total_open_risk", total_open_pct + actual_risk_pct <= config.max_total_open_risk_pct),
        ("max_correlated_risk", correlated_pct <= config.max_correlated_risk_pct),
        ("daily_loss_limit", daily_loss_pct < config.daily_loss_limit_pct),
        ("consecutive_loss_lock", loss_streak < config.max_consecutive_losses),
    ]
    failed = [name for name, passed in checks if not passed]

    return {
        "allow": not failed,
        "reason": "PASS" if not failed else ",".join(failed),
        "equity_usd": round(equity, 4),
        "risk_pct": round(actual_risk_pct, 6),
        "risk_usd": round(risk_usd, 4),
        "position_size": round(units, 10),
        "contract_size": spec.contract_size,
        "quote_to_usd": spec.quote_to_usd,
        "size_step": spec.size_step,
        "stop_distance": round(distance, 8),
        "rr": round(rr, 4),
        "open_positions": len(opens),
        "open_risk_usd": round(total_open, 4),
        "open_risk_pct": round(total_open_pct, 4),
        "correlated_risk_pct": round(correlated_pct, 4),
        "daily_realized_pnl_usd": round(daily_pnl, 4),
        "daily_loss_pct": round(daily_loss_pct, 4),
        "consecutive_losses": loss_streak,
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
