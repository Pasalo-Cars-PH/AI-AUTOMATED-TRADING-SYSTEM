from datetime import datetime, timezone
import math

import pytest

from app.risk_engine import (
    RiskConfig, evaluate_risk, position_size_units, realized_pnl_usd, realized_r,
    consecutive_losses, daily_realized_pnl_usd, open_risk_usd,
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
        {"status": "CLOSED", "result": "LOSS", "r": -1, "realized_pnl_usd": -100, "closed_at": "2026-10-09T01:00:00+00:00"},
        {"status": "CLOSED", "result": "LOSS", "r": -1, "realized_pnl_usd": -100, "closed_at": "2026-10-09T02:00:00+00:00"},
        {"status": "CLOSED", "result": "LOSS", "r": -1, "realized_pnl_usd": -100, "closed_at": "2026-10-09T03:00:00+00:00"},
        {"status": "CLOSED", "result": "LOSS", "r": -1, "realized_pnl_usd": -100, "closed_at": "2026-10-09T04:00:00+00:00"},
    ]
    r = evaluate_risk(
        trades, equity_usd=10000, entry=100, sl=98, tp=104, side="BUY",
        symbol="XAU/USD", config=RiskConfig(), instrument_spec=UNIT_SPEC
    )
    assert not r["allow"]
    assert "consecutive_loss_lock" in r["reason"]


def test_open_trade_without_risk_metadata_fails_closed():
    with pytest.raises(ValueError, match="open_trade_risk_usd"):
        open_risk_usd([{"status": "OPEN", "symbol": "XAU/USD"}])


def test_open_trade_nonpositive_risk_fails_closed():
    with pytest.raises(ValueError, match="open_trade_risk_usd"):
        open_risk_usd([{"status": "OPEN", "risk_usd": 0}])


def test_loss_streak_uses_realized_pnl_not_manual_result_label():
    trades = [
        {"status": "CLOSED", "result": "WIN", "realized_pnl_usd": -12, "closed_at": "2026-10-08T10:00:00+00:00"},
        {"status": "CLOSED", "result": "LOSS", "realized_pnl_usd": -4, "closed_at": "2026-10-08T11:00:00+00:00"},
    ]
    assert consecutive_losses(trades) == 2


def test_breakeven_resets_consecutive_loss_streak():
    trades = [
        {"status": "CLOSED", "realized_pnl_usd": -12, "closed_at": "2026-10-08T10:00:00+00:00"},
        {"status": "CLOSED", "realized_pnl_usd": 0, "closed_at": "2026-10-08T11:00:00+00:00"},
    ]
    assert consecutive_losses(trades) == 0


def test_closed_trade_without_realized_pnl_fails_closed():
    with pytest.raises(ValueError, match="closed_trade_realized_pnl"):
        consecutive_losses([{"status": "CLOSED", "result": "LOSS", "closed_at": "2026-10-08T10:00:00+00:00"}])


def test_daily_pnl_normalizes_timezone_before_day_comparison():
    # 00:30 UTC on Oct 9 is 08:30 PHT; the first close is Oct 9 UTC,
    # while the second is Oct 8 UTC despite having an Oct 9 PHT date.
    trades = [
        {"status": "CLOSED", "closed_at": "2026-10-09T08:00:00+08:00", "realized_pnl_usd": -25},
        {"status": "CLOSED", "closed_at": "2026-10-09T07:00:00+08:00", "realized_pnl_usd": -40},
    ]
    now = datetime(2026, 10, 9, 0, 30, tzinfo=timezone.utc)
    assert daily_realized_pnl_usd(trades, now) == -25


def test_risk_rejects_legacy_open_trade_without_risk_metadata():
    r = evaluate_risk(
        [{"status": "OPEN", "symbol": "EUR/USD"}],
        equity_usd=10000, entry=100, sl=98, tp=104, side="BUY",
        symbol="USD/JPY", config=RiskConfig(), instrument_spec=UNIT_SPEC,
    )
    assert not r["allow"]
    assert r["reason"].startswith("portfolio_data_integrity:")


def test_actual_risk_pct_reflects_rounded_position_size():
    spec = {"contract_size": 100, "quote_to_usd": 1, "size_step": 0.1}
    r = evaluate_risk(
        [], equity_usd=10000, entry=2000, sl=1998, tp=2004, side="BUY",
        symbol="XAU/USD", config=RiskConfig(), instrument_spec=spec,
    )
    assert r["allow"]
    assert r["risk_pct"] == pytest.approx(r["risk_usd"] / 10000 * 100)
    assert r["risk_pct"] <= 0.5


def test_non_finite_instrument_metadata_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        position_size_units(10000, 0.5, 100, 98, {
            "contract_size": math.inf, "quote_to_usd": 1, "size_step": 0.01,
        })


def test_invalid_risk_configuration_is_rejected():
    with pytest.raises(ValueError, match="risk_per_trade_pct"):
        RiskConfig(risk_per_trade_pct=math.nan)


def test_risk_per_trade_cannot_exceed_total_open_risk_limit():
    with pytest.raises(ValueError, match="cannot exceed"):
        RiskConfig(risk_per_trade_pct=4.0, max_total_open_risk_pct=3.0)


def test_correlated_risk_exact_boundary_is_rejected():
    trades = [{"status": "OPEN", "risk_usd": 100, "symbol": "XAU/USD"}]
    r = evaluate_risk(
        trades, equity_usd=10000, entry=100, sl=98, tp=104, side="BUY",
        symbol="XAU/USD", config=RiskConfig(), instrument_spec=UNIT_SPEC,
    )
    assert not r["allow"]
    assert "max_correlated_risk" in r["reason"]
    assert r["correlated_risk_pct"] == pytest.approx(1.5)
