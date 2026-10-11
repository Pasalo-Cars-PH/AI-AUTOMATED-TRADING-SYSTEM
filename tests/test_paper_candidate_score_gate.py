from app.paper_validation import create_candidate


def test_candidate_is_actionable_only_with_score_and_all_gates():
    signal = {
        "pair": "XAU/USD", "type": "BUY", "time": "2026-10-11T10:00:00Z",
        "entry": 2000, "sl": 1990, "tp": 2020, "rr": 2,
        "confluence_score": 100, "confluence_components": [],
    }
    candidate = create_candidate(signal, [{"name": "H1", "pass": True}])
    assert candidate["state"] == "ACTIONABLE"
    assert candidate["execution_mode"] == "PAPER_ONLY"


def test_candidate_fails_closed_when_score_missing_or_low():
    signal = {"pair": "XAU/USD", "type": "BUY", "confluence_score": 0}
    candidate = create_candidate(signal, [{"name": "H1", "pass": True}])
    assert candidate["state"] == "NO_TRADE"
    signal["confluence_score"] = 90
    candidate = create_candidate(signal, [{"name": "H1", "pass": True}, {"name": "M15", "pass": False}])
    assert candidate["state"] == "NO_TRADE"


def test_candidate_fails_closed_when_gate_list_empty():
    candidate = create_candidate({"confluence_score": 100}, [])
    assert candidate["state"] == "NO_TRADE"
