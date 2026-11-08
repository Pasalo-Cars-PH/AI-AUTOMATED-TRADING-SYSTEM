import pandas as pd
from unittest.mock import patch

from app.main import smc_signal


def _execution_bars():
    rows = []
    start = pd.Timestamp("2026-10-12 09:00:00")
    for i in range(40):
        rows.append({
            "datetime": start + pd.Timedelta(minutes=5 * i),
            "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
        })
    # The middle candle is a bearish displacement candle. Its high sweeps
    # PDH; the final closed candle leaves a bearish FVG.
    rows[-2].update({"open": 101.0, "high": 101.2, "low": 97.8, "close": 98.0})
    rows[-1].update({"open": 98.8, "high": 99.0, "low": 97.9, "close": 98.5})
    return rows


def test_smc_signal_uses_supplied_post_close_execution_entry_for_levels():
    rows = _execution_bars()
    with patch("app.main._atr_series", return_value=[1.0]):
        sig, checks = smc_signal(
            rows, pdh=100.8, pdl=95.0, entry_price=99.5, explain=True
        )

    assert sig is not None
    assert sig["type"] == "SELL"
    assert sig["entry"] == 99.5
    assert sig["tp"] == round(99.5 - 1.5 * abs(sig["sl"] - 99.5), 5)
    risk_gate = next(x for x in checks if x["name"] == "Risk size at executable entry")
    assert risk_gate["pass"] is True
    assert "entry=99.50000" in risk_gate["actual"]


def test_smc_signal_rejects_execution_entry_that_breaks_risk_bounds():
    rows = _execution_bars()
    with patch("app.main._atr_series", return_value=[1.0]):
        sig, checks = smc_signal(
            rows, pdh=100.8, pdl=95.0, entry_price=110.0, explain=True
        )

    assert sig is None
    risk_gate = next(x for x in checks if x["name"] == "Risk size at executable entry")
    assert risk_gate["pass"] is False
