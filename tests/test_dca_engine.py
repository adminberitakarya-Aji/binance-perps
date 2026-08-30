import unittest
from unittest.mock import MagicMock

from src.strategy.base import Signal
from src.risk.manager import RiskManager, RiskLimits
from src.config import Config


class TestSmartDCA(unittest.TestCase):
    def setUp(self):
        self.limits = RiskLimits(
            dca_enabled=True,
            dca_max_orders=3,
            dca_step_atr_mult=1.5,
            dca_lot_multiplier=1.0,
            dca_tp_rr_ratio=1.0,
            dca_hard_sl_equity_pct=0.03,
            use_trailing=True,
            trailing_start_atr_mult=1.2,
            trailing_distance_atr_mult=1.0,
            trailing_step_atr_mult=0.3,
        )
        self.rm = RiskManager(self.limits)

    def test_dca_trigger_buy(self):
        # Entry lapis 1 = 80,000, ATR = 200, required drop = 1.5 * 200 = 300
        # Trigger jika price <= 79,700
        self.assertFalse(self.rm.should_trigger_dca(Signal.BUY, 80000.0, 79800.0, 200.0, 1))
        self.assertTrue(self.rm.should_trigger_dca(Signal.BUY, 80000.0, 79700.0, 200.0, 1))
        self.assertTrue(self.rm.should_trigger_dca(Signal.BUY, 80000.0, 79650.0, 200.0, 1))

    def test_dca_trigger_sell(self):
        # Entry lapis 1 = 80,000, ATR = 200, required drop = 1.5 * 200 = 300
        # Trigger jika price >= 80,300
        self.assertFalse(self.rm.should_trigger_dca(Signal.SELL, 80000.0, 80200.0, 200.0, 1))
        self.assertTrue(self.rm.should_trigger_dca(Signal.SELL, 80000.0, 80300.0, 200.0, 1))
        self.assertTrue(self.rm.should_trigger_dca(Signal.SELL, 80000.0, 80350.0, 200.0, 1))

    def test_dca_max_orders_respected(self):
        # Sudah 3 lapis -> tidak boleh trigger lagi
        self.assertFalse(self.rm.should_trigger_dca(Signal.BUY, 80000.0, 78000.0, 200.0, 3))

    def test_dca_disabled_respected(self):
        self.rm.limits.dca_enabled = False
        self.assertFalse(self.rm.should_trigger_dca(Signal.BUY, 80000.0, 78000.0, 200.0, 1))

    def test_dca_avg_and_tp_computation_buy(self):
        # Lapis 1: 0.1 BTC @ 80,000
        # Lapis 2: 0.1 BTC @ 79,000
        # Avg Price = 79,500. Total Size = 0.2 BTC
        # TP = Avg Price + (1.0 * ATR 200) = 79,700
        layers = [
            {"price": 80000.0, "size": 0.1},
            {"price": 79000.0, "size": 0.1},
        ]
        avg_px, tot_sz, new_tp = self.rm.compute_dca_avg_and_tp(Signal.BUY, layers, 200.0)
        self.assertEqual(avg_px, 79500.0)
        self.assertAlmostEqual(tot_sz, 0.2)
        self.assertEqual(new_tp, 79700.0)

    def test_dca_avg_and_tp_computation_sell(self):
        # Lapis 1: 0.1 BTC @ 80,000
        # Lapis 2: 0.1 BTC @ 81,000
        # Avg Price = 80,500. Total Size = 0.2 BTC
        # TP = Avg Price - (1.0 * ATR 200) = 80,300
        layers = [
            {"price": 80000.0, "size": 0.1},
            {"price": 81000.0, "size": 0.1},
        ]
        avg_px, tot_sz, new_tp = self.rm.compute_dca_avg_and_tp(Signal.SELL, layers, 200.0)
        self.assertEqual(avg_px, 80500.0)
        self.assertAlmostEqual(tot_sz, 0.2)
        self.assertEqual(new_tp, 80300.0)

    def test_hard_sl_cut_loss(self):
        # Equity = $5,000. Hard SL = 3% = $150
        self.assertFalse(self.rm.is_hard_sl_triggered(100.0, 5000.0))
        self.assertTrue(self.rm.is_hard_sl_triggered(150.0, 5000.0))
        self.assertTrue(self.rm.is_hard_sl_triggered(200.0, 5000.0))

    def test_trailing_stop_from_average_price_buy(self):
        # Avg Price = 79,500, ATR = 200
        # Trailing start distance = 1.2 * 200 = 240 -> price harus >= 79,740
        # Saat price = 79,800: new_sl = 79,800 - (1.0 * 200) = 79,600
        current_sl = 79000.0
        new_sl = self.rm.compute_trailing_sl(Signal.BUY, 79500.0, 79800.0, current_sl, 200.0)
        self.assertEqual(new_sl, 79600.0)

        # Belum capai threshold profit (misal price = 79,600 < 79,740)
        self.assertIsNone(self.rm.compute_trailing_sl(Signal.BUY, 79500.0, 79600.0, current_sl, 200.0))

    def test_trailing_stop_from_average_price_sell(self):
        # Avg Price = 80,500, ATR = 200
        # Trailing start distance = 1.2 * 200 = 240 -> price harus <= 80,260
        # Saat price = 80,200: new_sl = 80,200 + (1.0 * 200) = 80,400
        current_sl = 81000.0
        new_sl = self.rm.compute_trailing_sl(Signal.SELL, 80500.0, 80200.0, current_sl, 200.0)
        self.assertEqual(new_sl, 80400.0)


if __name__ == "__main__":
    unittest.main()
