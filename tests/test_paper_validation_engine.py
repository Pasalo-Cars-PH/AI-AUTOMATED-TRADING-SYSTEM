from app.paper_validation import create_candidate, gate_summary, validate_transition


def test_lifecycle_transitions_are_deterministic():
    assert validate_transition("NO_TRADE", "TRIGGER")
    assert validate_transition("TRIGGER", "SETUP")
    assert validate_transition("SETUP", "ACTIONABLE")
    assert validate_transition("ACTIONABLE", "MANAGEMENT")
    assert validate_transition("MANAGEMENT", "JOURNAL")
    assert validate_transition("JOURNAL", "NO_TRADE")
    assert not validate_transition("NO_TRADE", "MANAGEMENT")


def test_gate_summary_rejects_any_failed_gate():
    gates = [
        {"name": "H1", "pass": True},
        {"name": "M15", "pass": False},
        {"name": "PAPER", "pass": True},
    ]
    summary = gate_summary(gates)
    assert summary["all_pass"] is False
    assert summary["passed"] == 2
    assert summary["failed_names"] == ["M15"]


def test_candidate_is_paper_only_and_auditable():
    signal = {
        "pair": "XAUUSD", "type": "BUY", "entry": 4000,
        "sl": 3990, "tp": 4020, "time": "2026-10-09 08:00:00",
        "version": "V8.0", "rr": 2.0
    }
    candidate = create_candidate(signal, [{"name": "H1", "pass": True}])
    assert candidate["state"] == "ACTIONABLE"
    assert candidate["execution_mode"] == "PAPER_ONLY"
    assert candidate["symbol"] == "XAUUSD"
    assert candidate["data_source"] == "LIVE_TWELVEDATA"
