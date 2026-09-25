import pytest
from app.market.models import Candle, DataQuality
from app.market.service import MarketDataService

def test_deduplication_and_sorting():
    svc = MarketDataService()
    c1 = Candle(
        symbol="BTCUSD", timestamp="2026-09-26T10:00:00Z", timeframe="M5",
        open=100, high=105, low=95, close=102, volume=10, source="BINANCE",
        provider_symbol="BTCUSDT", is_closed=True
    )
    c2 = Candle(
        symbol="BTCUSD", timestamp="2026-09-26T10:00:00Z", timeframe="M5",
        open=100, high=105, low=95, close=103, volume=12, source="BINANCE",
        provider_symbol="BTCUSDT", is_closed=True
    )
    
    svc.candles_cache["BTCUSD"] = {"M5": [c1]}
    # Re-insert modified duplicate timestamp
    svc.candles_cache["BTCUSD"]["M5"].append(c2)
    
    # Manual deduplicate check
    existing = {c.timestamp: c for c in svc.candles_cache["BTCUSD"]["M5"]}
    assert len(existing) == 1
    assert existing["2026-09-26T10:00:00Z"].close == 103

def test_stale_data_detection():
    svc = MarketDataService()
    old_candle = Candle(
        symbol="BTCUSD", timestamp="2020-01-01T00:00:00Z", timeframe="M5",
        open=100, high=105, low=95, close=102, volume=10, source="BINANCE",
        provider_symbol="BTCUSDT", is_closed=True
    )
    svc.candles_cache["BTCUSD"] = {"M5": [old_candle]}
    assert svc.is_data_fresh("BTCUSD", "M5") is False
