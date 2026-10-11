"""Deterministic paper-validation lifecycle.

This module contains state transitions only. It never submits broker orders.
"""

STATES = (
    "NO_TRADE",
    "TRIGGER",
    "SETUP",
    "ACTIONABLE",
    "MANAGEMENT",
    "JOURNAL",
)


def validate_transition(current, target):
    if current == target:
        return True
    allowed = {
        "NO_TRADE": {"TRIGGER"},
        "TRIGGER": {"SETUP", "NO_TRADE"},
        "SETUP": {"ACTIONABLE", "NO_TRADE"},
        "ACTIONABLE": {"MANAGEMENT", "NO_TRADE"},
        "MANAGEMENT": {"JOURNAL"},
        "JOURNAL": {"NO_TRADE"},
    }
    return target in allowed.get(current, set())


def create_candidate(signal, gates, data_source="LIVE_TWELVEDATA"):
    """Create an audit snapshot; fail closed unless every gate and score passes."""
    score = signal.get("confluence_score")
    try:
        score_ok = float(score) >= 75
    except (TypeError, ValueError):
        score_ok = False
    gates_ok = bool(gates) and all(bool(g.get("pass")) for g in gates)
    state = "ACTIONABLE" if score_ok and gates_ok else "NO_TRADE"
    return {
        "state": state,
        "execution_mode": "PAPER_ONLY",
        "signal_id": f"{signal.get('pair','UNKNOWN')}-{signal.get('time','UNKNOWN')}-{signal.get('type','UNKNOWN')}",
        "strategy": "SMC",
        "strategy_version": signal.get("version"),
        "symbol": signal.get("pair"),
        "side": signal.get("type"),
        "entry": signal.get("entry"),
        "sl": signal.get("sl"),
        "tp": signal.get("tp"),
        "rr": signal.get("rr"),
        "confluence_score": score if score_ok else None,
        "confluence_components": signal.get("confluence_components", []),
        "signal_time": signal.get("time"),
        "data_source": data_source,
        "gates": gates,
    }


def gate_summary(gates):
    passed = [g for g in gates if g.get("pass")]
    failed = [g for g in gates if not g.get("pass")]
    return {
        "passed": len(passed),
        "failed": len(failed),
        "all_pass": not failed,
        "failed_names": [g.get("name", "UNKNOWN") for g in failed],
    }
