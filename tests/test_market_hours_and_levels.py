import datetime as dt

from app.main import market_hours_status, smc_day_levels, smc_prev_map


def _bars(start, count, high=100.5, low=100.0, step_minutes=5):
    rows = []
    for i in range(count):
        stamp = start + dt.timedelta(minutes=i * step_minutes)
        rows.append({
            "datetime": stamp.strftime("%Y-%m-%d %H:%M:%S"),
            "open": low + 0.1,
            "high": high,
            "low": low,
            "close": low + 0.2,
        })
    return rows


def test_xau_market_guard_skips_sunday_before_session_open():
    now = dt.datetime(2026, 10, 18, 13, 15)  # Sunday UTC
    is_open, reason = market_hours_status("XAU/USD", now)
    assert is_open is False
    assert reason == "WEEKEND_SUNDAY_PREOPEN"


def test_crypto_market_guard_is_24_7_even_on_weekend():
    now = dt.datetime(2026, 10, 18, 13, 15)
    assert market_hours_status("BTCUSD", now) == (True, "CRYPTO_24_7")


def test_weekend_gap_does_not_replace_previous_valid_utc_trading_day():
    friday = dt.datetime(2026, 10, 16, 0, 0)
    saturday = dt.datetime(2026, 10, 17, 0, 0)
    sunday = dt.datetime(2026, 10, 18, 0, 0)
    monday = dt.datetime(2026, 10, 19, 0, 0)
    records = []
    records += _bars(friday, 100, high=4164.86, low=4164.61)
    records += _bars(saturday, 3, high=4165.0, low=4164.0)
    records += _bars(sunday, 3, high=4166.0, low=4163.0)
    records += _bars(monday, 3, high=4167.0, low=4162.0)

    levels = smc_day_levels(records)
    prev = smc_prev_map(levels)
    assert prev[monday.date()] == (4164.86, 4164.61)
    assert prev[sunday.date()] == (4164.86, 4164.61)


def test_previous_day_with_large_intraday_gap_is_rejected():
    friday = _bars(dt.datetime(2026, 10, 16, 0, 0), 50, high=101, low=100)
    # A second cluster separated by 8 hours creates a suspiciously incomplete day.
    friday += _bars(dt.datetime(2026, 10, 16, 9, 0), 50, high=101, low=100)
    monday = _bars(dt.datetime(2026, 10, 19, 0, 0), 3, high=102, low=99)
    prev = smc_prev_map(smc_day_levels(friday + monday))
    assert prev[dt.date(2026, 10, 19)] is None


def test_smc_signal_does_not_fetch_or_evaluate_gates_when_market_closed(monkeypatch):
    import app.main as app_main

    monkeypatch.setattr(app_main, "market_hours_status", lambda *args, **kwargs: (False, "WEEKEND_SUNDAY_PREOPEN"))

    def fail_if_fetched(*args, **kwargs):
        raise AssertionError("market data must not be fetched while market is closed")

    monkeypatch.setattr(app_main, "fetch_m5_live", fail_if_fetched)
    signal, checks, records = app_main.smc_live_signal(explain=True)
    assert signal is None
    assert records is None
    assert checks[0]["name"] == "Market hours"
    assert "MARKET_CLOSED, skip" in checks[0]["actual"]
