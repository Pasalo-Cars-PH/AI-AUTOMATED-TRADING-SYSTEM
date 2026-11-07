import unittest

from app.titan_v10.feature_adapter import build_features


def trend_bars(count=80):
    rows = []
    for i in range(count):
        close = 100.0 + i * 0.8
        rows.append({
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000 + i,
        })
    return rows


class TestFeatureAdapter(unittest.TestCase):
    def test_unsupported_checkpoints_stay_unavailable(self):
        features = build_features(trend_bars(), closed_candles_only=True, timeframe="M5")
        self.assertEqual(features["amd_vp"]["status"], "UNAVAILABLE")
        self.assertEqual(features["order_block"]["status"], "UNAVAILABLE")
        self.assertEqual(features["news_dxy"]["status"], "UNAVAILABLE")
        self.assertEqual(features["balance_rr"]["status"], "UNAVAILABLE")
        self.assertEqual(features["timeframe_alignment"]["status"], "UNAVAILABLE")

    def test_open_candle_rejected(self):
        features = build_features(trend_bars(), closed_candles_only=False, timeframe="M5")
        self.assertTrue(all(x["status"] == "UNAVAILABLE" for x in features.values()))
        self.assertIn("Open candle", features["ema_hybrid"]["reason"])

    def test_trend_indicators_emit_directional_features(self):
        features = build_features(trend_bars(), closed_candles_only=True, timeframe="M5")
        self.assertEqual(features["ema_hybrid"]["status"], "PASS")
        self.assertEqual(features["ema_hybrid"]["direction"], "BUY")
        self.assertEqual(features["macd"]["direction"], "BUY")
        self.assertEqual(features["rsi"]["direction"], "BUY")
        self.assertIn(features["adx"]["status"], {"PASS", "FAIL"})

    def test_missing_timeframe_is_not_silently_accepted(self):
        features = build_features(trend_bars(), closed_candles_only=True, timeframe="")
        self.assertEqual(features["ema_hybrid"]["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
