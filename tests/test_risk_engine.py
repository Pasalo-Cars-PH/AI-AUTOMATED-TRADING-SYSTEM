from app.risk_engine import (
    RiskConfig, evaluate_risk, position_size_units, realized_pnl_usd, realized_r,
)

UNIT_SPEC = {"contract_size": 1, "quote_to_usd": 1, "size_step": 0.01}


def test_position_size_uses_actual_stop_distance_and_contract_spec():
    assert position_size_units(10000, 0.5, 100, 98, UNIT_SPEC) == 25


def test_xau_contract_size_changes_lot_sizing():
    # $50 budget / (2.00 price distance * 100 oz/lot) = 0.25 lots.
    gold = {"contract_size": 100, "quote_to_usd": 1, "size_step": 0.01}
    assert position_size_units(10000, 0.5, 2000, 1998, gold) == 0.25


def test_size_rounds_down_to_valid_increment():
    spec = {"contract_size": 100, "quote_to_usd": 1, "size_step": 0.1}
    assert position_size_units(10000, 0.5, 2000, 1998, spec) == 0.2


def test_missing_instrument_spec_fails_closed():
    r = evaluate_risk(
        [], equity_usd=10000, entry=100, sl=98, tp=104, side="BUY",
        symbol="UNKNOWN", config=RiskConfig(), instrument_spec=None
    )
    assert not r["allow"]
    assert r["reason"] == "missing_or_invalid_instrument_spec"


def test_risk_rejects_bad_rr():
    r = evaluate_risk(
        [], equity_usd=10000, entry=100, sl=99, tp=100.5, side="BUY",
        symbol="XAU/USD", config=RiskConfig(), instrument_spec=UNIT_SPEC
    )
    assert not r["allow"]
    assert "rr" in r["reason"]


def test_total_open_risk_gate():
    trades = [
        {"status": "OPEN", "risk_usd": 200, "symbol": "XAU/USD"},
        {"status": "OPEN", "risk_usd": 100, "symbol": "EUR/USD"},
    ]
    r = evaluate_risk(
        trades, equity_usd=10000, entry=100, sl=98, tp=104, side="BUY",
        symbol="USD/JPY", config=RiskConfig(), instrument_spec=UNIT_SPEC
    )
    assert not r["allow"]
    assert "max_total_open_risk" in r["reason"]


def test_correlated_risk_gate():
    trades = [{"status": "OPEN", "risk_usd": 110, "symbol": "XAU/USD"}]
    r = evaluate_risk(
        trades, equity_usd=10000, entry=100, sl=98, tp=104, side="BUY",
        symbol="XAU/USD", config=RiskConfig(), instrument_spec=UNIT_SPEC
    )
    assert not r["allow"]
    assert "max_correlated_risk" in r["reason"]


def test_actual_exit_pnl_and_r_use_contract_metadata():
    trade = {
        "type": "BUY", "entry": 100, "sl": 98, "risk_usd": 100,
        "position_size": 0.5, "contract_size": 100, "quote_to_usd": 1,
    }
    assert realized_pnl_usd(trade, 104) == 200
    assert realized_r(trade, 104) == 2


def test_no_trade_when_loss_lock_is_reached():
    trades = [
        {"status": "CLOSED", "result": "LOSS", "r": -1, "closed_at": "2026-10-09T01:00:00+00:00"},
        {"status": "CLOSED", "result": "LOSS", "r": -1, "closed_at": "2026-10-09T02:00:00+00:00"},
        {"status": "CLOSED", "result": "LOSS", "r": -1, "closed_at": "2026-10-09T03:00:00+00:00"},
        {"status": "CLOSED", "result": "LOSS", "r": -1, "closed_at": "2026-10-09T04:00:00+00:00"},
    ]
    r = evaluate_risk(
        trades, equity_usd=10000, entry=100, sl=98, tp=104, side="BUY",
        symbol="XAU/USD", config=RiskConfig(), instrument_spec=UNIT_SPEC
    )
    assert not r["allow"]
    assert "consecutive_loss_lock" in r["reason"]
