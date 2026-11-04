import unittest
from app.titan_v10.indicators import ema,rsi,macd,adx,true_ranges
from app.titan_v10.structure import confirmed_swings,fair_value_gaps,liquidity_sweeps,structure_break

class TestIndicators(unittest.TestCase):
 def test_ema_constant(self): self.assertAlmostEqual(ema([10]*30,10),10)
 def test_rsi_up_only(self): self.assertEqual(rsi(list(range(20)),14),100)
 def test_rsi_flat(self): self.assertEqual(rsi([5]*20,14),50)
 def test_macd_flat(self): self.assertAlmostEqual(macd([10]*60)["histogram"],0)
 def test_adx_flat(self): self.assertAlmostEqual(adx([10]*40,[10]*40,[10]*40,14)["adx"],0)
 def test_true_range(self): self.assertEqual(true_ranges([11,13],[9,10],[10,12]),[3,3])
 def test_ema_short_input_rejected(self):
  with self.assertRaises(ValueError): ema([1,2],3)

class TestStructure(unittest.TestCase):
 def setUp(self): self.bars=[{"open":10+i*.1,"high":11+i*.1,"low":9+i*.1,"close":10+i*.1} for i in range(30)]
 def test_monotonic_has_no_pivot(self): self.assertEqual(confirmed_swings(self.bars)["swing_highs"],[])
 def test_bullish_fvg(self):
  b=[{"open":1,"high":2,"low":.5,"close":1.5},{"open":1.5,"high":2.5,"low":1,"close":2},{"open":3,"high":4,"low":3,"close":3.5}]
  self.assertEqual(fair_value_gaps(b)[0]["direction"],"BUY")
 def test_sweep_reclaim(self):
  b=[{"open":10,"high":11,"low":9,"close":10} for _ in range(20)]; b.append({"open":10,"high":12,"low":9.5,"close":10.5})
  self.assertEqual(liquidity_sweeps(b)[0]["direction"],"SELL")
 def test_structure_unavailable(self): self.assertEqual(structure_break(self.bars)["status"],"UNAVAILABLE")

if __name__=="__main__": unittest.main()
