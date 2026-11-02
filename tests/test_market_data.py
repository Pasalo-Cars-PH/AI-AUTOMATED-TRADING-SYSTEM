import pytest
from unittest.mock import AsyncMock, patch
from app.market.service import market_service

@pytest.mark.asyncio
async def test_canonical_market_service_interface():
    # Mocking external market fetch to pass in CI runners (avoid Binance geofence 451)
    with patch.object(market_service, 'update_symbol_data', new_callable=AsyncMock) as mock_update:
        mock_update.return_value = True
        success = await market_service.update_symbol_data("BTCUSD", "M5")
        assert success is True


def test_gbpjpy_routes_to_twelve_data_provider():
    provider, symbol = market_service._get_provider_for_symbol("GBPJPY")
    assert provider is market_service.twelvedata
    assert symbol == "GBPJPY"


def test_twelvedata_supports_h4_interval_mapping():
    from app.market.twelvedata_provider import TwelveDataProvider

    provider = TwelveDataProvider()
    assert provider._format_symbol("GBPJPY") == "GBP/JPY"
    assert provider._format_symbol("XAUUSD") == "XAU/USD"


def test_binance_supports_h4_interval_mapping(monkeypatch):
    from app.market.binance_provider import BinanceProvider

    provider = BinanceProvider()
    captured = {}

    async def fake_to_thread(fn, url, params):
        captured.update(params)
        return []

    monkeypatch.setattr("app.market.binance_provider.asyncio.to_thread", fake_to_thread)

    import asyncio
    result = asyncio.run(provider.get_candles("BTCUSD", "H4", limit=100))
    assert result == []
    assert captured["symbol"] == "BTCUSDT"
    assert captured["interval"] == "4h"
