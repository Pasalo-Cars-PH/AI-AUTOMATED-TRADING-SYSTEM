#!/usr/bin/env python3
"""Export the same Twelve Data XAU/USD M5 payload requested by app.main.fetch_data.

Usage (from repository root, with TWELVE_DATA_API_KEY in the environment):
    python scripts/export_xauusd_m5.py
    python scripts/export_xauusd_m5.py --csv reports/xauusd_m5_900.csv --report reports/xauusd_m5_audit.md

The export intentionally calls fetch_data("XAU/USD", "5min", 900) directly,
not the cached wrapper. No strategy settings or execution flags are modified.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import inspect
import os
import sys
from pathlib import Path
from typing import Any

UTC = dt.timezone.utc
EXPECTED_PDH = 4164.86
EXPECTED_PDL = 4164.61
COLUMNS = ("datetime", "open", "high", "low", "close")


def as_utc_timestamp(value: Any) -> dt.datetime:
    """Parse timezone=UTC timestamps; naive values are interpreted as UTC."""
    parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def line_of(function: Any) -> str:
    try:
        _, line = inspect.getsourcelines(function)
        return f"{inspect.getsourcefile(function)}:{line}"
    except (OSError, TypeError):
        return "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="reports/xauusd_m5_900.csv", help="CSV output path")
    parser.add_argument("--report", default="reports/xauusd_m5_audit.md", help="Markdown report path")
    args = parser.parse_args()

    try:
        from app import main as app_main
    except Exception as exc:
        print(f"ERROR: could not import app.main: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not os.getenv("TWELVE_DATA_API_KEY"):
        print("ERROR: TWELVE_DATA_API_KEY is not set in this process environment.", file=sys.stderr)
        print("Set it in the trusted runtime environment; do not paste or commit the key.", file=sys.stderr)
        return 3

    request_started = dt.datetime.now(UTC)
    try:
        raw = app_main.fetch_data("XAU/USD", "5min", 900)
    except Exception as exc:
        print(f"ERROR: fetch_data raised {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4
    request_finished = dt.datetime.now(UTC)

    if not raw:
        print("ERROR: fetch_data returned no candles; inspect the preceding Twelve Data/API log.", file=sys.stderr)
        return 5

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        missing = [key for key in COLUMNS if key not in item]
        if missing:
            print(f"ERROR: candle row {index} missing required fields: {missing}", file=sys.stderr)
            return 6
        stamp = as_utc_timestamp(item["datetime"])
        rows.append({
            "datetime": stamp.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "_ts": stamp,
        })

    rows.sort(key=lambda row: row["_ts"])
    now = dt.datetime.now(UTC)
    first_ts, last_ts = rows[0]["_ts"], rows[-1]["_ts"]
    close_boundary = last_ts + dt.timedelta(minutes=5)
    closed = close_boundary <= now
    now_floor = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)

    previous_utc_day = now.date() - dt.timedelta(days=1)
    previous_day_rows = [r for r in rows if r["_ts"].date() == previous_utc_day]
    pdh = max((r["high"] for r in previous_day_rows), default=None)
    pdl = min((r["low"] for r in previous_day_rows), default=None)
    day_coverage = (
        f"{len(previous_day_rows)} candles dated {previous_utc_day.isoformat()}; interval completeness not guaranteed"
        if previous_day_rows else
        f"no rows dated {previous_utc_day.isoformat()}; cannot recompute previous UTC day's levels from this window"
    )

    csv_path, report_path = Path(args.csv), Path(args.report)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in COLUMNS})

    cache_key = ("XAU/USD".upper(), "5min", 900)
    cache = getattr(app_main, "_twelve_data_cache", {})
    cached = cache.get(cache_key)
    cache_age = None
    if cached and cached.get("time"):
        try:
            cache_time = cached["time"]
            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=UTC)
            cache_age = (now - cache_time.astimezone(UTC)).total_seconds()
        except Exception:
            cache_age = None

    functions = {
        "fetch_data": getattr(app_main, "fetch_data", None),
        "fetch_data_with_fallback": getattr(app_main, "fetch_data_with_fallback", None),
        "fetch_live_tf": getattr(app_main, "fetch_live_tf", None),
        "smc_day_levels": getattr(app_main, "smc_day_levels", None),
        "smc_prev_map": getattr(app_main, "smc_prev_map", None),
    }
    source_locations = {name: line_of(fn) for name, fn in functions.items() if fn is not None}
    source_excerpt = []
    for name, fn in functions.items():
        if fn is not None:
            try:
                source_excerpt.append(f"### {name}\n\n~~~python\n{inspect.getsource(fn).rstrip()}\n~~~")
            except (OSError, TypeError):
                source_excerpt.append(f"### {name}\n\nSource unavailable via inspect.")

    pdh_comparison = "NOT COMPUTED: no candles on previous UTC date" if pdh is None else (
        f"computed PDH={pdh:.2f}; reference={EXPECTED_PDH:.2f}; delta={pdh - EXPECTED_PDH:+.2f}"
    )
    pdl_comparison = "NOT COMPUTED: no candles on previous UTC date" if pdl is None else (
        f"computed PDL={pdl:.2f}; reference={EXPECTED_PDL:.2f}; delta={pdl - EXPECTED_PDL:+.2f}"
    )
    report = f"""# XAU/USD M5 900-candle export and PDH/PDL audit

- Generated at (UTC): {now.isoformat()}
- Source: Twelve Data through app.main.fetch_data("XAU/USD", "5min", 900)
- Request duration: {(request_finished - request_started).total_seconds():.3f}s (wall time around function call; HTTP metadata is not exposed)
- Requested response timezone: UTC (existing fetch function sends timezone=UTC)
- Response timezone metadata: not exposed by fetch_data; returned datetime strings are naive. This script interprets them as UTC because UTC is explicitly requested. Provider response metadata cannot be independently verified through this function's return value.
- Row count exported: {len(rows)}
- First timestamp UTC: {first_ts.isoformat()}
- Last timestamp UTC: {last_ts.isoformat()}
- Current time UTC: {now.isoformat()}
- Last candle close boundary (open timestamp + 5 minutes): {close_boundary.isoformat()}
- Closed-candle check: {"PASS" if closed else "FAIL — last candle may still be forming"} (close boundary <= now)
- Current M5 boundary floor UTC: {now_floor.isoformat()}
- Previous UTC calendar day for recompute: {previous_utc_day.isoformat()}
- Previous-day sample coverage: {day_coverage}
- PDH comparison: {pdh_comparison}
- PDL comparison: {pdl_comparison}
- Direct fetch cache behavior: export calls fetch_data directly, bypassing _twelve_data_cache wrapper.
- Production wrapper cache TTL: 120 seconds (per fetch_data_with_fallback source).
- Stale-cache diagnostic: {"entry age exceeds 120s (stale by wrapper TTL)" if cache_age is not None and cache_age >= 120 else "matching process-local entry is younger than 120s" if cache_age is not None else "no matching process-local cache entry; stale status unavailable"}.
- Production wrapper cache key inspected: {cache_key}
- Matching wrapper cache entry present in this process: {"yes" if cached else "no"}
- Matching wrapper cache age: {f"{cache_age:.3f}s" if cache_age is not None else "unavailable/no matching entry"}
- Cache note: this process-local cache check does not reveal a separate Render worker's cache.
- Source locations: {", ".join(f"{k}={v}" for k, v in source_locations.items())}
- PDH/PDL production logic: smc_day_levels groups highs/lows by parsed date; smc_prev_map selects the latest prior day having at least 100 bars. Compare this production behavior with the independently computed previous UTC calendar-day extrema above.
- API key: read from TWELVE_DATA_API_KEY; never written to output.

## Interpretation limits

PDH/PDL are valid only if the export contains the intended complete previous UTC calendar day. This script computes extrema from all exported rows dated that day, but 900 M5 bars may cover only part of it. The row count is not proof that every 5-minute interval is present. Candle timestamps are treated as candle-open timestamps.

## Source excerpts

{chr(10).join(source_excerpt)}
"""
    report_path.write_text(report, encoding="utf-8")
    print(f"CSV: {csv_path}")
    print(f"Report: {report_path}")
    print(f"Rows: {len(rows)}")
    print(f"First timestamp UTC: {first_ts.isoformat()}")
    print(f"Last timestamp UTC: {last_ts.isoformat()}")
    print(f"Closed candle: {closed} (last + 5m={close_boundary.isoformat()}, now={now.isoformat()})")
    print(f"Previous UTC day: {previous_utc_day.isoformat()} ({day_coverage})")
    print(f"PDH: {pdh_comparison}")
    print(f"PDL: {pdl_comparison}")
    print(f"Cache key: {cache_key}; age: {f'{cache_age:.3f}s' if cache_age is not None else 'unavailable'}")
    print(f"Source locations: {source_locations}")
    print("Production PDH/PDL functions: smc_day_levels and smc_prev_map; see report for file/line and source excerpts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
