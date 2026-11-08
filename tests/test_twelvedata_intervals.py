import unittest
from unittest.mock import patch, Mock

from app.market.twelvedata_provider import TwelveDataProvider


class TestTwelveDataIntervals(unittest.IsolatedAsyncioTestCase):
    async def test_supported_timeframes_map_to_provider_intervals(self):
        cases = {
            "M5": "5min",
            "M15": "15min",
            "H1": "1h",
            "H4": "4h",
            "D1": "1day",
        }
        provider = TwelveDataProvider()
        provider.api_key = "test-key"
        payload = {"values": [{"datetime": "2026-11-08 00:00:00",
                               "open": "100", "high": "101", "low": "99",
                               "close": "100.5", "volume": "10"}]}
        response = Mock(status_code=200)
        response.json.return_value = payload
        for timeframe, expected in cases.items():
            with self.subTest(timeframe=timeframe):
                with patch("app.market.twelvedata_provider.requests.get", return_value=response) as get:
                    await provider.get_candles("XAUUSD", timeframe, limit=10)
                    self.assertEqual(get.call_args.kwargs["params"]["interval"], expected)

    async def test_unknown_timeframe_is_rejected_without_request(self):
        provider = TwelveDataProvider()
        provider.api_key = "test-key"
        with patch("app.market.twelvedata_provider.requests.get") as get:
            result = await provider.get_candles("XAUUSD", "M7", limit=10)
        self.assertEqual(result, [])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
