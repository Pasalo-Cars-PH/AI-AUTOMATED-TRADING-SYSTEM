import datetime as dt

import app.main as app_main


class _FixedDateTime(dt.datetime):
    fixed_now = dt.datetime(2026, 11, 8, 12, 0, 0)

    @classmethod
    def utcnow(cls):
        return cls.fixed_now


def _provider_rows(count, interval_minutes, last_open):
    rows = []
    for i in range(count):
        stamp = last_open - dt.timedelta(minutes=interval_minutes * i)
        close = 100.0 + i * 0.01
        rows.append({
            "datetime": stamp.strftime("%Y-%m-%d %H:%M:%S"),
            "open": str(close - 0.01),
            "high": str(close + 0.1),
            "low": str(close - 0.1),
            "close": str(close),
            "volume": "10",
        })
    return rows


def test_m15_alignment_rejects_stale_closed_candles(monkeypatch):
    monkeypatch.setattr(app_main.datetime, "datetime", _FixedDateTime)
    now = _FixedDateTime.fixed_now
    # Last M15 bar closed one hour ago, beyond the 45-minute freshness budget.
    rows = _provider_rows(100, 15, now - dt.timedelta(minutes=75))
    monkeypatch.setattr(app_main, "fetch_data", lambda *args, **kwargs: rows)

    trend, source = app_main.fetch_m15_trend()

    assert trend == "UNKNOWN"
    assert source == "STALE_OR_FUTURE"


def test_m15_alignment_accepts_fresh_closed_candles(monkeypatch):
    monkeypatch.setattr(app_main.datetime, "datetime", _FixedDateTime)
    now = _FixedDateTime.fixed_now
    rows = _provider_rows(100, 15, now - dt.timedelta(minutes=30))
    monkeypatch.setattr(app_main, "fetch_data", lambda *args, **kwargs: rows)

    trend, source = app_main.fetch_m15_trend()

    assert trend in {"BULL", "BEAR", "NEUTRAL"}
    assert source == "LIVE_TWELVEDATA_15min"


def test_h1_alignment_rejects_stale_closed_candles(monkeypatch):
    monkeypatch.setattr(app_main.datetime, "datetime", _FixedDateTime)
    now = _FixedDateTime.fixed_now
    rows = _provider_rows(100, 60, now - dt.timedelta(hours=5))
    monkeypatch.setattr(app_main, "fetch_data_with_fallback", lambda *args, **kwargs: (rows, "TEST"))

    assert app_main.fetch_h1_supertrend_adx() is None
