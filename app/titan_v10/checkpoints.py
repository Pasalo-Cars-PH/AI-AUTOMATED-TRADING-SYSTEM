"""TITAN V10 20-checkpoint confluence framework.

This module is deliberately side-effect free. It does not fetch data, place orders,
change V9.0 behavior, or infer missing market features. Upstream adapters must supply
validated, closed-candle features. Missing inputs remain UNAVAILABLE.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Mapping


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Checkpoint:
    id: int
    name: str
    group: str
    weight: int
    feature: str
    direction: str = "neutral"
    hard_gate: bool = False


@dataclass(frozen=True)
class CheckResult:
    id: int
    name: str
    status: Status
    score: int
    max_score: int
    reason: str


@dataclass(frozen=True)
class Decision:
    direction: str
    status: str
    score: float
    available_weight: int
    passed: int
    failed: int
    unavailable: int
    hard_gate_failures: tuple[str, ...]
    checkpoints: tuple[CheckResult, ...]


CHECKPOINTS = (
    Checkpoint(1, "AMD + Volume Profile", "regime", 5, "amd_vp"),
    Checkpoint(2, "EMA Hybrid", "trend", 6, "ema_hybrid", direction="directional"),
    Checkpoint(3, "RSI", "momentum", 3, "rsi", direction="directional"),
    Checkpoint(4, "MACD", "momentum", 3, "macd", direction="directional"),
    Checkpoint(5, "ADX", "momentum", 3, "adx"),
    Checkpoint(6, "BOS / CHOCH", "structure", 6, "bos_choch", direction="directional"),
    Checkpoint(7, "Fair Value Gap", "structure", 5, "fvg", direction="directional"),
    Checkpoint(8, "Order Block", "structure", 5, "order_block", direction="directional"),
    Checkpoint(9, "Spring / Upthrust", "regime", 4, "spring_upthrust", direction="directional"),
    Checkpoint(10, "OTE", "location", 4, "ote", direction="directional"),
    Checkpoint(11, "Kill Zones", "timing", 4, "killzone", hard_gate=True),
    Checkpoint(12, "News + DXY", "macro", 5, "news_dxy", hard_gate=True),
    Checkpoint(13, "Dynamic Management", "management", 0, "dynamic_management"),
    Checkpoint(14, "Wyckoff Phase", "regime", 4, "wyckoff", direction="directional"),
    Checkpoint(15, "Balance + RR", "risk", 5, "balance_rr", hard_gate=True),
    Checkpoint(16, "Volume + Imbalance", "volume", 5, "volume_imbalance"),
    Checkpoint(17, "S/R + Supply / Demand", "location", 5, "sr_supply_demand", direction="directional"),
    Checkpoint(18, "Liquidity Sweep", "liquidity", 7, "liquidity_sweep", direction="directional"),
    Checkpoint(19, "Market Structure", "structure", 7, "market_structure", direction="directional"),
    Checkpoint(20, "Timeframe Alignment", "mtf", 9, "timeframe_alignment", direction="directional", hard_gate=True),
)

# Each feature must be a mapping with status PASS/FAIL and a non-empty reason.
# Directional features additionally require direction BUY or SELL.
DIRECTIONAL = {c.feature for c in CHECKPOINTS if c.direction == "directional" and c.weight > 0}


def _normalize(feature: Any, checkpoint: Checkpoint, direction: str) -> tuple[Status, str]:
    if not isinstance(feature, Mapping):
        return Status.UNAVAILABLE, "Validated feature input not supplied"
    raw_status = str(feature.get("status", "")).upper()
    if raw_status not in {s.value for s in Status}:
        return Status.UNAVAILABLE, "Feature status missing or invalid"
    status = Status(raw_status)
    reason = str(feature.get("reason") or ("Validated condition met" if status == Status.PASS else "Condition not met"))
    if status == Status.UNAVAILABLE:
        return status, reason
    if checkpoint.feature in DIRECTIONAL:
        observed = str(feature.get("direction", "")).upper()
        if observed not in {"BUY", "SELL"}:
            return Status.UNAVAILABLE, "Directional feature has no valid BUY/SELL direction"
        if observed != direction:
            return Status.FAIL, f"Opposing direction: {observed}"
    return status, reason


def evaluate(features: Mapping[str, Any], direction: str, *,
             min_score: float = 75.0, min_rr: float = 2.0,
             data_valid: bool = True, closed_candles_only: bool = True) -> Decision:
    """Evaluate one side independently. No missing input can become a pass."""
    direction = direction.upper()
    if direction not in {"BUY", "SELL"}:
        raise ValueError("direction must be BUY or SELL")
    if not 0 <= min_score <= 100:
        raise ValueError("min_score must be between 0 and 100")
    if min_rr <= 0:
        raise ValueError("min_rr must be positive")

    results = []
    hard_failures = []
    available_weight = earned_weight = 0
    for cp in CHECKPOINTS:
        if cp.weight == 0:  # management is a post-entry process, not entry confluence
            status, reason = Status.UNAVAILABLE, "Post-entry management; excluded from entry score"
        elif not data_valid:
            status, reason = Status.UNAVAILABLE, "Market data integrity gate failed"
        elif not closed_candles_only:
            status, reason = Status.UNAVAILABLE, "Only closed candles may be evaluated"
        else:
            status, reason = _normalize(features.get(cp.feature), cp, direction)

        if cp.feature == "balance_rr" and status == Status.PASS:
            rr = features.get("balance_rr", {}).get("rr")
            if not isinstance(rr, (int, float)) or rr < min_rr:
                status, reason = Status.FAIL, f"RR below required minimum {min_rr:g}"

        if cp.weight:
            if status != Status.UNAVAILABLE:
                available_weight += cp.weight
                if status == Status.PASS:
                    earned_weight += cp.weight
            if cp.hard_gate and status != Status.PASS:
                hard_failures.append(f"{cp.name}: {reason}")
        results.append(CheckResult(cp.id, cp.name, status,
                                   cp.weight if status == Status.PASS else 0,
                                   cp.weight, reason))

    # Normalize against total configured entry weight, not only available features.
    total_weight = sum(c.weight for c in CHECKPOINTS)
    score = 100.0 * earned_weight / total_weight
    passed = sum(r.status == Status.PASS for r in results)
    failed = sum(r.status == Status.FAIL for r in results)
    unavailable = sum(r.status == Status.UNAVAILABLE for r in results)
    if not data_valid or not closed_candles_only:
        decision_status = "REJECT_DATA"
    elif hard_failures:
        decision_status = "REJECT_GATE"
    elif score < min_score:
        decision_status = "INSUFFICIENT_CONFLUENCE"
    elif available_weight < total_weight:
        decision_status = "INCOMPLETE_DATA"
    else:
        decision_status = "PAPER_CANDIDATE"
    return Decision(direction, decision_status, round(score, 2), available_weight,
                    passed, failed, unavailable, tuple(hard_failures), tuple(results))


def decision_dict(decision: Decision) -> dict[str, Any]:
    """JSON-friendly serialization for API/Telegram adapters."""
    payload = asdict(decision)
    payload["checkpoints"] = [
        {**asdict(item), "status": item.status.value} for item in decision.checkpoints
    ]
    return payload
