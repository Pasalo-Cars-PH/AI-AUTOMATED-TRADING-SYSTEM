import datetime as dt
import os
from zoneinfo import ZoneInfo

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


def _utc_for_local(value):
    return dt.datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(dt.timezone.utc)


def test_market_hours_friday_close_saturday_and_sunday_boundaries(monkeypatch):
    monkeypatch.setenv("MARKET_TIMEZONE", "America/New_York")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-23T16:59")) == (True, "SESSION_OPEN")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-23T17:00")) == (False, "WEEKEND_FRIDAY_AFTER_CLOSE")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-24T12:00")) == (False, "WEEKEND_SATURDAY")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-25T16:59")) == (False, "WEEKEND_SUNDAY_PREOPEN")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-25T17:00")) == (False, "WEEKEND_SUNDAY_PREOPEN")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-25T17:59")) == (False, "WEEKEND_SUNDAY_PREOPEN")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-25T18:00")) == (True, "SESSION_OPEN")


def test_market_hours_daily_break_and_crypto_weekend(monkeypatch):
    monkeypatch.setenv("MARKET_TIMEZONE", "America/New_York")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-20T17:30")) == (False, "DAILY_MAINTENANCE_BREAK")
    assert market_hours_status("XAU/USD", _utc_for_local("2026-10-20T18:00")) == (True, "SESSION_OPEN")
    assert market_hours_status("BTCUSD", _utc_for_local("2026-10-24T12:00")) == (True, "CRYPTO_24_7")


def test_market_hours_follow_dst_transition_automatically(monkeypatch):
    monkeypatch.setenv("MARKET_TIMEZONE", "America/New_York")
    # Same broker-local Sunday open maps to 22:00 UTC before spring DST and 21:00 UTC after.
    assert market_hours_status("XAU/USD", dt.datetime(2026, 3, 8, 21, 59, tzinfo=dt.timezone.utc)) == (False, "WEEKEND_SUNDAY_PREOPEN")
    assert market_hours_status("XAU/USD", dt.datetime(2026, 3, 8, 22, 0, tzinfo=dt.timezone.utc)) == (True, "SESSION_OPEN")
    assert market_hours_status("XAU/USD", dt.datetime(2026, 11, 1, 22, 59, tzinfo=dt.timezone.utc)) == (False, "WEEKEND_SUNDAY_PREOPEN")
    assert market_hours_status("XAU/USD", dt.datetime(2026, 11, 1, 23, 0, tzinfo=dt.timezone.utc)) == (True, "SESSION_OPEN")


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
    prev = smc_prev_map(smc_day_levels(records))
    assert prev[monday.date()] == (4164.86, 4164.61)
    assert prev[sunday.date()] == (4164.86, 4164.61)


def test_zero_range_day_is_rejected():
    friday = _bars(dt.datetime(2026, 10, 16, 0, 0), 100, high=100.0, low=100.0)
    monday = _bars(dt.datetime(2026, 10, 19, 0, 0), 3, high=102.0, low=99.0)
    assert smc_prev_map(smc_day_levels(friday + monday))[dt.date(2026, 10, 19)] is None


def test_previous_day_with_large_intraday_gap_is_rejected():
    friday = _bars(dt.datetime(2026, 10, 16, 0, 0), 50, high=101, low=100)
    friday += _bars(dt.datetime(2026, 10, 16, 9, 0), 50, high=101, low=100)
    monday = _bars(dt.datetime(2026, 10, 19, 0, 0), 3, high=102, low=99)
    assert smc_prev_map(smc_day_levels(friday + monday))[dt.date(2026, 10, 19)] is None


def test_smc_signal_does_not_fetch_or_evaluate_gates_when_market_closed(monkeypatch):
    import app.main as app_main
    monkeypatch.setattr(app_main, "market_hours_status", lambda *args, **kwargs: (False, "WEEKEND_SUNDAY_PREOPEN"))
    def fail_if_fetched(*args, **kwargs):
        raise AssertionError("market data must not be fetched while market is closed")
    monkeypatch.setattr(app_main, "fetch_m5_live", fail_if_fetched)
    signal, checks, records = app_main.smc_live_signal(explain=True)
    assert signal is None and records is None
    assert checks[0]["name"] == "Market hours"
    assert "MARKET_CLOSED, skip" in checks[0]["actual"]



def test_auto_scan_job_uses_one_defined_utc_timestamp_for_killzone(monkeypatch):
    import app.main as app_main

    fixed_now = dt.datetime(2026, 10, 20, 12, 4, 59)
    class FixedDateTime:
        @staticmethod
        def utcnow():
            return fixed_now

    monkeypatch.setattr(app_main.datetime, "datetime", FixedDateTime)
    monkeypatch.setattr(app_main, "MASTER_LIVE_ENABLE", False)
    monkeypatch.setattr(app_main, "PAPER_SCAN_PAUSED", False)
    monkeypatch.setattr(app_main, "TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setattr(app_main, "STRATEGY", "SMC")
    monkeypatch.setattr(app_main, "market_hours_status", lambda symbol, now: (True, "SESSION_OPEN"))
    observed = []
    monkeypatch.setattr(app_main, "in_killzone", lambda hour: observed.append(hour) or True)
    monkeypatch.setattr(app_main, "smc_scan", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_main, "_record_scan_heartbeat", lambda *args, **kwargs: None)

    app_main.auto_scan_job()
    assert observed == [11]
