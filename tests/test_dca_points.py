"""Test DCA dan TPSL mode Point / Poin Fixed Dollar ($)."""

import unittest
from src.strategy.base import Signal
from src.risk.manager import RiskManager, RiskLimits


class TestPointMode(unittest.TestCase):
    def setUp(self):
        self.limits = RiskLimits(
            tpsl_mode="point",
            sl_points=300.0,
            tp_points=450.0,
            dca_enabled=True,
            dca_max_orders=3,
            dca_step_points=200.0,
            dca_tp_points=250.0,
            dca_lot_multiplier=1.0,
            risk_per_trade_pct=0.01,
            max_leverage=3.0,
        )
        self.rm = RiskManager(self.limits)

    def test_compute_sl_tp_single_entry(self):
        self.limits.dca_enabled = False
        entry = 80000.0
        sl, tp = self.rm.compute_sl_tp(Signal.BUY, entry, atr=0.0)
        self.assertEqual(sl, 79700.0)  # 80000 - 300
        self.assertEqual(tp, 80450.0)  # 80000 + 450

        sl_sell, tp_sell = self.rm.compute_sl_tp(Signal.SELL, entry, atr=0.0)
        self.assertEqual(sl_sell, 80300.0)  # 80000 + 300
        self.assertEqual(tp_sell, 79550.0)  # 80000 - 450

    def test_compute_sl_tp_with_dca(self):
        self.limits.dca_enabled = True
        entry = 80000.0
        # total drop = 3 * 200 + 300 = 900
        sl, tp = self.rm.compute_sl_tp(Signal.BUY, entry, atr=0.0)
        self.assertEqual(sl, 79100.0)  # 80000 - 900
        self.assertEqual(tp, 80450.0)  # 80000 + 450

    def test_should_trigger_dca(self):
        last_price = 80000.0
        # step = 200 -> harga harus <= 79800
        self.assertFalse(self.rm.should_trigger_dca(Signal.BUY, last_price, 79850.0, 0.0, 1))
        self.assertTrue(self.rm.should_trigger_dca(Signal.BUY, last_price, 79800.0, 0.0, 1))
        self.assertTrue(self.rm.should_trigger_dca(Signal.BUY, last_price, 79750.0, 0.0, 1))
        # max orders reached
        self.assertFalse(self.rm.should_trigger_dca(Signal.BUY, last_price, 79000.0, 0.0, 3))

    def test_compute_dca_grid_plan(self):
        entry = 80000.0
        base_size = 100.0
        equity = 1000.0
        grid = self.rm.compute_dca_grid_plan(Signal.BUY, entry, base_size, 0.0, equity)
        self.assertEqual(len(grid), 2)  # Lapis 2 dan 3
        self.assertEqual(grid[0]["layer"], 2)
        self.assertEqual(grid[0]["price"], 79800.0)  # 80000 - 200
        self.assertEqual(grid[1]["layer"], 3)
        self.assertEqual(grid[1]["price"], 79600.0)  # 79800 - 200

    def test_compute_dca_avg_and_tp(self):
        layers = [
            {"price": 80000.0, "size": 0.01},
            {"price": 79800.0, "size": 0.01},
        ]
        avg_px, total_sz, tp = self.rm.compute_dca_avg_and_tp(Signal.BUY, layers, 0.0)
        self.assertEqual(avg_px, 79900.0)
        self.assertAlmostEqual(total_sz, 0.02)
        self.assertEqual(tp, 80150.0)  # 79900 + 250 (dca_tp_points)

    def test_point_trailing_buy(self):
        self.limits.use_trailing = True
        self.limits.trailing_start_points = 200.0
        self.limits.trailing_lock_points = 100.0
        self.limits.trailing_step_points = 100.0
        self.limits.trailing_move_points = 50.0

        avg_entry = 80000.0
        initial_sl = 79100.0

        # 1. Profit +150 (belum capai 200) -> None
        sl1 = self.rm.compute_trailing_sl(Signal.BUY, avg_entry, 80150.0, initial_sl, 0.0)
        self.assertIsNone(sl1)

        # 2. Profit +200 (Trigger 1) -> SL dikunci di 80100 (+100)
        sl2 = self.rm.compute_trailing_sl(Signal.BUY, avg_entry, 80200.0, initial_sl, 0.0)
        self.assertEqual(sl2, 80100.0)

        # 3. Harga naik ke +250 (belum sampai milestone 300) -> SL tetap 80100 (tidak ada new SL > current_sl)
        sl3 = self.rm.compute_trailing_sl(Signal.BUY, avg_entry, 80250.0, 80100.0, 0.0)
        self.assertIsNone(sl3)

        # 4. Harga naik ke +300 (Trigger 2: +1 step) -> SL naik ke 80150 (+100 + 50)
        sl4 = self.rm.compute_trailing_sl(Signal.BUY, avg_entry, 80300.0, 80100.0, 0.0)
        self.assertEqual(sl4, 80150.0)

        # 5. Harga naik ke +400 (Trigger 3: +2 step) -> SL naik ke 80200 (+100 + 100)
        sl5 = self.rm.compute_trailing_sl(Signal.BUY, avg_entry, 80400.0, 80150.0, 0.0)
        self.assertEqual(sl5, 80200.0)

        # 6. Harga melonjak ke +550 (3 step penuh) -> SL naik ke 80250 (+100 + 150)
        sl6 = self.rm.compute_trailing_sl(Signal.BUY, avg_entry, 80550.0, 80200.0, 0.0)
        self.assertEqual(sl6, 80250.0)

        # 7. Harga koreksi turun ke +450 -> SL tidak turun
        sl7 = self.rm.compute_trailing_sl(Signal.BUY, avg_entry, 80450.0, 80250.0, 0.0)
        self.assertIsNone(sl7)

    def test_point_trailing_sell(self):
        self.limits.use_trailing = True
        self.limits.trailing_start_points = 200.0
        self.limits.trailing_lock_points = 100.0
        self.limits.trailing_step_points = 100.0
        self.limits.trailing_move_points = 50.0

        avg_entry = 80000.0
        initial_sl = 80900.0

        # 1. Profit +150 (turun ke 79850) -> None
        sl1 = self.rm.compute_trailing_sl(Signal.SELL, avg_entry, 79850.0, initial_sl, 0.0)
        self.assertIsNone(sl1)

        # 2. Profit +200 (turun ke 79800) -> SL dikunci di 79900 (-100)
        sl2 = self.rm.compute_trailing_sl(Signal.SELL, avg_entry, 79800.0, initial_sl, 0.0)
        self.assertEqual(sl2, 79900.0)

        # 3. Profit +300 (turun ke 79700) -> SL turun ke 79850 (-150)
        sl3 = self.rm.compute_trailing_sl(Signal.SELL, avg_entry, 79700.0, 79900.0, 0.0)
        self.assertEqual(sl3, 79850.0)


if __name__ == "__main__":
    unittest.main()
