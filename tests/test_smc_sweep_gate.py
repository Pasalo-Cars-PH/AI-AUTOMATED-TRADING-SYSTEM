import pandas as pd

from app.main import smc_signal


def _bars(*, recent_high=4190.0, recent_low=4186.0, final_close=4190.0):
    """Deterministic candles for gate tests only; never used as market data."""
    rows = []
    start = pd.Timestamp("2026-10-12 09:00:00")
    for i in range(40):
        close = 4190.0
        rows.append({
            "datetime": start + pd.Timedelta(minutes=5 * i),
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
        })
    # Place the potential sweep in the 12 bars before the final candle.
    rows[-2].update({"open": 4187.0, "high": recent_high, "low": recent_low, "close": 4188.0})
    rows[-1].update({"open": final_close - 0.2, "high": final_close + 0.2,
                     "low": final_close - 0.3, "close": final_close})
    return rows


def test_pdl_sweep_requires_close_back_above_pdl():
    rows = _bars(recent_low=4180.0, final_close=4186.0)
    _, checks = smc_signal(rows, pdh=4200.0, pdl=4184.0, explain=True)
    sweep = next(c for c in checks if c["name"] == "Sweep PDH/PDL")
    assert sweep["pass"] is True


def test_pdl_break_without_reclaim_fails_sweep_gate():
    rows = _bars(recent_low=4180.0, final_close=4182.0)
    _, checks = smc_signal(rows, pdh=4200.0, pdl=4184.0, explain=True)
    sweep = next(c for c in checks if c["name"] == "Sweep PDH/PDL")
    assert sweep["pass"] is False


def test_pdh_sweep_requires_close_back_below_pdh():
    rows = _bars(recent_high=4205.0, final_close=4198.0)
    _, checks = smc_signal(rows, pdh=4200.0, pdl=4184.0, explain=True)
    sweep = next(c for c in checks if c["name"] == "Sweep PDH/PDL")
    assert sweep["pass"] is True


def test_pdh_break_without_reclaim_fails_sweep_gate():
    rows = _bars(recent_high=4205.0, final_close=4202.0)
    _, checks = smc_signal(rows, pdh=4200.0, pdl=4184.0, explain=True)
    sweep = next(c for c in checks if c["name"] == "Sweep PDH/PDL")
    assert sweep["pass"] is False


def test_missing_prior_day_levels_fail_closed():
    rows = _bars()
    _, checks = smc_signal(rows, pdh=None, pdl=None, explain=True)
    level_gate = next(c for c in checks if c["name"] == "PDH/PDL")
    assert level_gate["pass"] is False
