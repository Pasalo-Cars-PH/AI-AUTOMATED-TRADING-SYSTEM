import pytest
import pandas as pd
from app.gates import (
    evaluate_calibrated_candidate,
    check_data_quality_gate,
    check_rr_gate,
    calculate_calibrated_confluence_score
)

@pytest.fixture
def dummy_ohlc():
    data = {'Close': [100.0 + i for i in range(60)]}
    return pd.DataFrame(data)

# TEST 1: Analytical factor failure alone does NOT block execution if score >= 75
def test_analytical_failure_alone_permits_trade(dummy_ohlc):
    # MTF is False, but total score is 78/100 (>= 75)
    analytical_factors = {
        "trend_aligned": True,      # 15
        "structure_strong": True,   # 15
        "mtf_aligned": False,       # 0 (MTF Failed)
        "sr_confluence": True,      # 10
        "price_action_valid": True, # 10
        "entry_quality_high": True, # 10
        "momentum_confirmed": True, # 10
        "volatility_healthy": True, # 8
        "rr_score_bonus": False,    # 0
        "data_quality_bonus": True  # 5 -> Total: 78
    }
    state, reason, score, _ = evaluate_calibrated_candidate(
        symbol="BTC-USD", df=dummy_ohlc, m5_action="BUY",
        entry=100.0, sl=90.0, tp=125.0, m5_candle_closed=True,
        analytical_factors=analytical_factors, master_enable=True, kill_switch=False
    )
    assert score == 78
    assert state == "ACTIONABLE_PAPER_PASS"

# TEST 2: Hard Safety Gate Failure (R:R < 1:1.5) ALWAYS blocks execution
def test_hard_gate_rr_failure_blocks(dummy_ohlc):
    analytical_factors = {k: True for k in ["trend_aligned", "structure_strong", "mtf_aligned", "sr_confluence", "price_action_valid", "entry_quality_high", "momentum_confirmed", "volatility_healthy", "rr_score_bonus", "data_quality_bonus"]}
    state, reason, score, _ = evaluate_calibrated_candidate(
        symbol="BTC-USD", df=dummy_ohlc, m5_action="BUY",
        entry=100.0, sl=95.0, tp=105.0, # R:R is 1:1.0 (< 1:1.5)
        m5_candle_closed=True, analytical_factors=analytical_factors, master_enable=True, kill_switch=False
    )
    assert state == "REJECTED"
    assert "RR_GATE" in reason

# TEST 3: Score < 75 ALWAYS blocks execution
def test_low_confluence_score_blocks(dummy_ohlc):
    analytical_factors = {"trend_aligned": True, "structure_strong": True} # Score = 30
    state, reason, score, _ = evaluate_calibrated_candidate(
        symbol="BTC-USD", df=dummy_ohlc, m5_action="BUY",
        entry=100.0, sl=90.0, tp=125.0, m5_candle_closed=True,
        analytical_factors=analytical_factors, master_enable=True, kill_switch=False
    )
    assert score < 75
    assert state == "REJECTED"
    assert "CONFLUENCE_SCORE_BELOW_THRESHOLD" in reason

# TEST 4: M5 Candle Unclosed results in WATCH state
def test_unclosed_m5_results_in_watch(dummy_ohlc):
    analytical_factors = {k: True for k in ["trend_aligned", "structure_strong", "mtf_aligned", "sr_confluence", "price_action_valid", "entry_quality_high", "momentum_confirmed", "volatility_healthy", "rr_score_bonus", "data_quality_bonus"]}
    state, reason, score, _ = evaluate_calibrated_candidate(
        symbol="BTC-USD", df=dummy_ohlc, m5_action="BUY",
        entry=100.0, sl=90.0, tp=125.0, m5_candle_closed=False, # Candle NOT closed
        analytical_factors=analytical_factors, master_enable=True, kill_switch=False
    )
    assert state == "WATCH"
    assert reason == "M5_CANDLE_UNCLOSED"

# TEST 5: Kill Switch / Master Enable False ALWAYS blocks
def test_execution_lock_blocks(dummy_ohlc):
    analytical_factors = {k: True for k in ["trend_aligned", "structure_strong", "mtf_aligned", "sr_confluence", "price_action_valid", "entry_quality_high", "momentum_confirmed", "volatility_healthy", "rr_score_bonus", "data_quality_bonus"]}
    state, reason, score, _ = evaluate_calibrated_candidate(
        symbol="BTC-USD", df=dummy_ohlc, m5_action="BUY",
        entry=100.0, sl=90.0, tp=125.0, m5_candle_closed=True,
        analytical_factors=analytical_factors, master_enable=False, kill_switch=True
    )
    assert state == "REJECTED"
    assert "EXECUTION_LOCK_ACTIVE" in reason
