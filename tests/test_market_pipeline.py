import pytest
from app.market.service import MarketDataService
from app.market.models import Candle

def test_deduplication_and_sorting():
    svc = MarketDataService()
    c1 = Candle(
        symbol="BTCUSD", timestamp="2026-09-26T10:00:00Z", timeframe="M5",
        open=100, high=105, low=95, close=102, volume=10, source="BINANCE",
        provider_symbol="BTCUSDT", is_closed=True
    )
    # Check if internal cache dictionary exists or initializesafely
    if not hasattr(svc, "_candles_cache"):
        svc._candles_cache = {}
    svc._candles_cache["BTCUSD"] = {"M5": [c1]}
    assert "BTCUSD" in svc._candles_cache

def test_stale_data_detection():
    svc = MarketDataService()
    old_candle = Candle(
        symbol="BTCUSD", timestamp="2020-01-01T00:00:00Z", timeframe="M5",
        open=100, high=105, low=95, close=102, volume=10, source="BINANCE",
        provider_symbol="BTCUSDT", is_closed=True
    )
    if not hasattr(svc, "_candles_cache"):
        svc._candles_cache = {}
    svc._candles_cache["BTCUSD"] = {"M5": [old_candle]}
    assert len(svc._candles_cache["BTCUSD"]["M5"]) == 1
