import unittest

from app.titan_v10.checkpoints import CHECKPOINTS, Status, evaluate, decision_dict


def all_pass(direction="BUY"):
    data = {}
    for cp in CHECKPOINTS:
        if cp.weight == 0:
            continue
        data[cp.feature] = {"status": "PASS", "reason": "unit test", "direction": direction}
    data["balance_rr"]["rr"] = 2.5
    return data


class TestTitanV10Checkpoints(unittest.TestCase):
    def test_registry_has_exactly_twenty_unique_checkpoints(self):
        self.assertEqual(len(CHECKPOINTS), 20)
        self.assertEqual(len({c.id for c in CHECKPOINTS}), 20)
        self.assertEqual(len({c.feature for c in CHECKPOINTS}), 20)

    def test_missing_features_are_unavailable_not_pass(self):
        result = evaluate({}, "BUY")
        self.assertEqual(result.status, "REJECT_GATE")
        self.assertTrue(all(
            item.status == Status.UNAVAILABLE
            for item in result.checkpoints if item.weight > 0
        ))

    def test_all_valid_passes_produce_paper_candidate_only(self):
        result = evaluate(all_pass(), "BUY")
        self.assertEqual(result.status, "PAPER_CANDIDATE")
        self.assertEqual(result.score, 100.0)
        self.assertFalse(result.hard_gate_failures)

    def test_opposite_direction_fails_directional_feature(self):
        features = all_pass("BUY")
        result = evaluate(features, "SELL")
        self.assertEqual(result.status, "REJECT_GATE")
        ema = next(x for x in result.checkpoints if x.id == 2)
        self.assertEqual(ema.status, Status.FAIL)
        self.assertIn("Opposing direction", ema.reason)

    def test_rr_below_floor_fails_hard_gate(self):
        features = all_pass()
        features["balance_rr"]["rr"] = 1.5
        result = evaluate(features, "BUY", min_rr=2.0)
        self.assertEqual(result.status, "REJECT_GATE")
        self.assertTrue(any("Balance + RR" in x for x in result.hard_gate_failures))

    def test_unclosed_candle_rejects_all_market_features(self):
        result = evaluate(all_pass(), "BUY", closed_candles_only=False)
        self.assertEqual(result.status, "REJECT_DATA")
        self.assertEqual(result.score, 0.0)

    def test_invalid_data_rejects(self):
        result = evaluate(all_pass(), "BUY", data_valid=False)
        self.assertEqual(result.status, "REJECT_DATA")

    def test_management_is_not_counted_as_entry_score(self):
        result = evaluate(all_pass(), "BUY")
        management = next(x for x in result.checkpoints if x.id == 13)
        self.assertEqual(management.status, Status.UNAVAILABLE)
        self.assertEqual(management.max_score, 0)

    def test_serialization_is_json_friendly(self):
        result = evaluate(all_pass(), "BUY")
        payload = decision_dict(result)
        self.assertEqual(payload["direction"], "BUY")
        self.assertEqual(payload["checkpoints"][0]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
