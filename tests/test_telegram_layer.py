import pytest
from app.telegram import handle_telegram_command, is_authorized
from app.gates import evaluate_calibrated_candidate

@pytest.fixture
def base_state():
    return {"master_enable": False, "kill_switch": True, "mode": "PAPER"}

@pytest.fixture
def daily_stats():
    return {
        "total_scans": 127,
        "candidate_setups": 8,
        "paper_executions": 0,
        "rejected_candidates": 8,
        "watch_candidates": 5,
        "rejection_breakdown": {"M5 Confirmation": 3, "R:R": 2, "News": 1, "Risk": 1, "Structure": 1},
        "scores": [76, 78, 80, 74, 76]
    }

def test_status_command(base_state, daily_stats):
    payload = {"message": {"chat": {"id": 12345}, "text": "/status"}}
    res = handle_telegram_command(payload, base_state, daily_stats)
    assert res["status"] == "success"
    assert res["command"] == "/status"

def test_lasttrade_no_trades(base_state, daily_stats):
    payload = {"message": {"chat": {"id": 12345}, "text": "/lasttrade"}}
    res = handle_telegram_command(payload, base_state, daily_stats, last_trade=None)
    assert res["status"] == "success"

def test_forbidden_unlock_attempt_preserves_strict_execution_lock(base_state, daily_stats):
    """SECURITY TEST: /unlock command MUST NOT mutate system state."""
    payload = {"message": {"chat": {"id": 12345}, "text": "/unlock"}}
    res = handle_telegram_command(payload, base_state, daily_stats)
    
    assert res["status"] == "blocked"
    # State remains immutable
    assert base_state["master_enable"] == False
    assert base_state["kill_switch"] == True
    assert base_state["mode"] == "PAPER"

def test_forbidden_buy_attempt(base_state, daily_stats):
    """SECURITY TEST: /buy XAUUSD command MUST NOT execute any order."""
    payload = {"message": {"chat": {"id": 12345}, "text": "/buy XAUUSD"}}
    res = handle_telegram_command(payload, base_state, daily_stats)
    assert res["status"] == "blocked"
