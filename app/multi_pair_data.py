"""Provider adapters for TITAN's multi-pair, signal-only market-data layer.

This module intentionally does not create orders, positions, or Telegram alerts.
It returns normalized, completed OHLCV candles only. Strategy gates remain in
app.main and must be run before any signal is emitted.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any

import requests

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
HTTP_TIMEOUT = (5, 20)

# Display symbol -> provider and provider-native symbol.
PAIR_ROUTES = {
    "BTC/USD": ("binance", "BTCUSDT"),
    "ETH/USD": ("binance", "ETHUSDT"),
    "SOL/USD": ("binance", "SOLUSDT"),
    "XAU/USD": ("twelvedata", "XAU/USD"),
    "EUR/USD": ("twelvedata", "EUR/USD"),
    "GBP/USD": ("twelvedata", "GBP/USD"),
    "USD/JPY": ("twelvedata", "USD/JPY"),
    "AUD/USD": ("twelvedata", "AUD/USD"),
    "USD/CAD": ("twelvedata", "USD/CAD"),
    "USD/CHF": ("twelvedata", "USD/CHF"),
    "NZD/USD": ("twelvedata", "NZD/USD"),
    "GBP/JPY": ("twelvedata", "GBP/JPY"),
}

INTERVALS = {
    "5min": ("5m", 5),
    "15min": ("15m", 15),
    "1h": ("1h", 60),
    "4h": ("4h", 240),
}


class MarketDataError(RuntimeError):
    """Raised when a provider cannot supply valid live candles."""


def _utc_naive(value: Any) -> dt.datetime:
    stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return stamp


def _normalize(rows: list[dict[str, Any]], symbol: str, provider: str,
               interval_minutes: int, now: dt.datetime | None = None) -> list[dict[str, Any]]:
    now = now or dt.datetime.utcnow()
    out = []
    for row in rows:
        try:
            stamp = _utc_naive(row["datetime"])
            candle = {
                "datetime": stamp,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0),
                "symbol": symbol,
                "provider": provider,
            }
            if not all(candle[k] > 0 for k in ("open", "high", "low", "close")):
                continue
            if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
                continue
            if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
                continue
            # Only completed bars: the bar-open timestamp plus its duration
            # must be at or before the current UTC time.
            if stamp + dt.timedelta(minutes=interval_minutes) <= now:
                out.append(candle)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    out.sort(key=lambda item: item["datetime"])
    deduped = {}
    for candle in out:
        deduped[candle["datetime"]] = candle
    return list(deduped.values())


def fetch_pair_candles(symbol: str, interval: str = "5min", outputsize: int = 300,
                       session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Fetch fresh candles for a supported pair; never fabricates fallback data."""
    display = symbol.upper().replace(" ", "")
    if display not in PAIR_ROUTES:
        raise MarketDataError(f"UNSUPPORTED_SYMBOL:{display}")
    if interval not in INTERVALS:
        raise MarketDataError(f"UNSUPPORTED_INTERVAL:{interval}")
    if not isinstance(outputsize, int) or outputsize < 60 or outputsize > 5000:
        raise MarketDataError("INVALID_OUTPUTSIZE")
    provider, native_symbol = PAIR_ROUTES[display]
    http = session or requests.Session()
    interval_minutes = INTERVALS[interval][1]
    try:
        if provider == "binance":
            response = http.get(
                BINANCE_KLINES_URL,
                params={"symbol": native_symbol, "interval": INTERVALS[interval][0],
                        "limit": min(outputsize, 1000)},
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise MarketDataError(f"BINANCE_BAD_RESPONSE:{display}")
            rows = [{
                "datetime": dt.datetime.fromtimestamp(item[0] / 1000, tz=dt.timezone.utc).isoformat(),
                "open": item[1], "high": item[2], "low": item[3], "close": item[4],
                "volume": item[5],
            } for item in payload]
        else:
            api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
            if not api_key:
                raise MarketDataError("TWELVE_DATA_API_KEY_NOT_SET")
            response = http.get(
                TWELVE_DATA_URL,
                params={"symbol": native_symbol, "interval": interval,
                        "outputsize": outputsize, "timezone": "UTC", "apikey": api_key},
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("values"), list):
                message = payload.get("message", "invalid response") if isinstance(payload, dict) else "invalid response"
                raise MarketDataError(f"TWELVE_DATA_BAD_RESPONSE:{display}:{message}")
            rows = payload["values"]
        candles = _normalize(rows, display, provider, interval_minutes)
        if len(candles) < 60:
            raise MarketDataError(
                f"INSUFFICIENT_CLOSED_CANDLES:{display}:{interval}:"
                f"{len(candles)}"
            )
        return candles[-outputsize:]
    except requests.RequestException as exc:
        raise MarketDataError(f"PROVIDER_REQUEST_FAILED:{display}:{provider}:{type(exc).__name__}") from exc


def pair_data_health() -> dict[str, dict[str, str]]:
    """Non-secret route inventory for diagnostics and command responses."""
    return {
        symbol: {"provider": route[0], "provider_symbol": route[1]}
        for symbol, route in PAIR_ROUTES.items()
    }
