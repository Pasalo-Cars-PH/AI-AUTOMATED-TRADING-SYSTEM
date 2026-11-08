import datetime as dt

from app.main import _validated_closed_m5_records


def test_v9_m5_rows_are_sorted_deduplicated_and_closed_only():
    now = dt.datetime(2026, 11, 8, 12, 19, 59)
    rows = [
        {"datetime": "2026-11-08 12:10:00", "open": "100", "high": "102", "low": "99", "close": "101"},
        {"datetime": "2026-11-08 12:00:00", "open": "98", "high": "100", "low": "97", "close": "99"},
        {"datetime": "2026-11-08 12:00:00", "open": "98", "high": "101", "low": "97", "close": "100"},
        {"datetime": "2026-11-08 12:15:00", "open": "101", "high": "103", "low": "100", "close": "102"},
    ]

    result = _validated_closed_m5_records(rows, now=now)

    assert [x["datetime"].strftime("%H:%M") for x in result] == ["12:00", "12:10"]
    assert result[0]["close"] == 100.0
    assert all(x["datetime"].tzinfo is None for x in result)


def test_v9_m5_rejects_invalid_ohlc_nonfinite_and_future_rows():
    now = dt.datetime(2026, 11, 8, 12, 19, 59)
    rows = [
        {"datetime": "2026-11-08 12:00:00", "open": "100", "high": "98", "low": "99", "close": "101"},
        {"datetime": "2026-11-08 12:05:00", "open": "100", "high": "102", "low": "99", "close": "nan"},
        {"datetime": "2026-11-08 12:15:00", "open": "101", "high": "103", "low": "100", "close": "102"},
        {"datetime": "2026-11-08 12:20:00", "open": "102", "high": "104", "low": "101", "close": "103"},
    ]

    assert _validated_closed_m5_records(rows, now=now) == []


def test_v9_m5_normalizes_timezone_aware_provider_timestamps_to_utc():
    now = dt.datetime(2026, 11, 8, 12, 20, 0)
    rows = [
        {"datetime": "2026-11-08 20:10:00+08:00", "open": "100", "high": "102", "low": "99", "close": "101"},
    ]

    result = _validated_closed_m5_records(rows, now=now)

    assert len(result) == 1
    assert result[0]["datetime"] == dt.datetime(2026, 11, 8, 12, 10)
