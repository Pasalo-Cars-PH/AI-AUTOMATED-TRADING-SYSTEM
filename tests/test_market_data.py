import pytest
from app.market.service import market_service

@pytest.mark.asyncio
async def test_canonical_market_service_interface():
    # 1. Test update & get_candles
    success = await market_service.update_symbol_data("BTCUSD", "M5")
    assert success is True
    
    candles = market_service.get_candles("BTCUSD", "M5")
    assert isinstance(candles, list)
    assert len(candles) > 0

    # 2. Test get_latest_closed_candle
    closed_candle = market_service.get_latest_closed_candle("BTCUSD", "M5")
    assert closed_candle is not None
    assert "close" in closed_candle

    # 3. Test Unsupported symbol handling
    unsupported_success = await market_service.update_symbol_data("UNSUPPORTED_XYZ", "M5")
    assert unsupported_success is False

    # 4. Test Health Endpoint Observability
    health = market_service.get_health()
    assert "BTCUSD_M5" in health
    assert health["BTCUSD_M5"]["status"] == "OK"
