from mt5_executor.config import Settings
def test_live_mode_rejected():
    try: Settings(mode="LIVE").validate()
    except RuntimeError: return
    assert False
def test_risk_above_one_percent_rejected():
    try: Settings(risk_pct=1.01).validate()
    except ValueError: return
    assert False
def test_threshold_fixed_at_80():
    try: Settings(min_score=79).validate()
    except ValueError: return
    assert False
def test_lot_cap():
    try: Settings(max_forex_lot=0.03).validate()
    except ValueError: return
    assert False
