import pytest
import pandas as pd
from app.gates import evaluate_calibrated_candidate

@pytest.fixture
def dummy_ohlc():
    data = {'Close': [100.0 + i for i in range(60)]}
    return pd.DataFrame(data)

def test_paper_override_blocked_in_live_mode(dummy_ohlc):
    """SECURITY INVARIANT: paper_override MUST FAIL if trading_mode is LIVE."""
    analytical_factors = {k: True for k in ["trend_aligned", "structure_strong", "mtf_aligned", "sr_confluence", "price_action_valid", "entry_quality_high", "momentum_confirmed", "volatility_healthy", "rr_score_bonus", "data_quality_bonus"]}
    state, reason, _, _ = evaluate_calibrated_candidate(
        symbol="BTC-USD", df=dummy_ohlc, m5_action="BUY",
        entry=100.0, sl=90.0, tp=125.0, m5_candle_closed=True,
        analytical_factors=analytical_factors,
        master_enable=False, kill_switch=True,
        trading_mode="LIVE", is_paper_override=True  # Security Violation Attempt
    )
    assert state == "REJECTED"
    assert "SECURITY_VIOLATION_PAPER_OVERRIDE_FORBIDDEN_IN_LIVE_MODE" in reason

def test_paper_override_permitted_in_paper_mode(dummy_ohlc):
    """Verifies paper override works strictly when trading_mode is PAPER."""
    analytical_factors = {k: True for k in ["trend_aligned", "structure_strong", "mtf_aligned", "sr_confluence", "price_action_valid", "entry_quality_high", "momentum_confirmed", "volatility_healthy", "rr_score_bonus", "data_quality_bonus"]}
    state, reason, score, gates = evaluate_calibrated_candidate(
        symbol="BTC-USD", df=dummy_ohlc, m5_action="BUY",
        entry=100.0, sl=90.0, tp=125.0, m5_candle_closed=True,
        analytical_factors=analytical_factors,
        master_enable=False, kill_switch=True,
        trading_mode="PAPER", is_paper_override=True
    )
    assert state == "ACTIONABLE_PAPER_PASS"
    assert reason == "NONE"
    assert gates["execution_lock"] == "PASS"
