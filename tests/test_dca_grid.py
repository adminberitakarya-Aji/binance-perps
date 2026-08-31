"""Unit tests untuk sistem Pre-placed Limit Orders (Grid DCA)."""

import unittest
from unittest.mock import MagicMock

from src.strategy.base import Signal
from src.risk.manager import RiskManager, RiskLimits


def _make_rm(tpsl_mode="pct", dca_max_orders=3, dca_step_pct=0.5,
             dca_step_atr_mult=1.5, dca_lot_multiplier=1.0,
             max_leverage=3.0, tp_pct=1.0):
    limits = RiskLimits(
        dca_enabled=True,
        dca_max_orders=dca_max_orders,
        dca_step_pct=dca_step_pct,
        dca_step_atr_mult=dca_step_atr_mult,
        dca_lot_multiplier=dca_lot_multiplier,
        dca_tp_rr_ratio=1.0,
        dca_hard_sl_equity_pct=0.03,
        max_leverage=max_leverage,
        tpsl_mode=tpsl_mode,
        tp_pct=tp_pct,
        use_trailing=False,
    )
    return RiskManager(limits)


class TestComputeDcaGridPlanPct(unittest.TestCase):

    def test_buy_pct_two_layers(self):
        rm = _make_rm(tpsl_mode="pct", dca_max_orders=3, dca_step_pct=0.5)
        grid = rm.compute_dca_grid_plan(Signal.BUY, 80000, 1000, 200, 10000)
        self.assertEqual(len(grid), 2)
        self.assertAlmostEqual(grid[0]["price"], 79600.0, places=1)
        self.assertEqual(grid[0]["layer"], 2)
        self.assertAlmostEqual(grid[1]["price"], 79202.0, places=0)
        self.assertEqual(grid[1]["layer"], 3)

    def test_sell_pct_two_layers(self):
        rm = _make_rm(tpsl_mode="pct", dca_max_orders=3, dca_step_pct=0.5)
        grid = rm.compute_dca_grid_plan(Signal.SELL, 80000, 1000, 200, 10000)
        self.assertEqual(len(grid), 2)
        self.assertAlmostEqual(grid[0]["price"], 80400.0, places=1)
        self.assertAlmostEqual(grid[1]["price"], 80802.0, places=0)

    def test_single_extra_layer(self):
        rm = _make_rm(tpsl_mode="pct", dca_max_orders=2, dca_step_pct=1.0)
        grid = rm.compute_dca_grid_plan(Signal.BUY, 100000, 500, 0, 5000)
        self.assertEqual(len(grid), 1)
        self.assertAlmostEqual(grid[0]["price"], 99000.0, places=1)

    def test_disabled_returns_empty(self):
        rm = _make_rm()
        rm.limits.dca_enabled = False
        self.assertEqual(rm.compute_dca_grid_plan(Signal.BUY, 80000, 1000, 200, 10000), [])

    def test_max_orders_one_returns_empty(self):
        rm = _make_rm(dca_max_orders=1)
        self.assertEqual(rm.compute_dca_grid_plan(Signal.BUY, 80000, 1000, 200, 10000), [])

    def test_lot_multiplier_applied(self):
        rm = _make_rm(tpsl_mode="pct", dca_max_orders=3, dca_step_pct=0.5, dca_lot_multiplier=1.5)
        grid = rm.compute_dca_grid_plan(Signal.BUY, 80000, 1000, 200, 10000)
        self.assertAlmostEqual(grid[0]["size_usd"], 1500.0, places=1)
        self.assertAlmostEqual(grid[1]["size_usd"], 2250.0, places=1)

    def test_size_asset_computed_from_price(self):
        rm = _make_rm(tpsl_mode="pct", dca_max_orders=2, dca_step_pct=1.0)
        grid = rm.compute_dca_grid_plan(Signal.BUY, 100000, 1000, 0, 5000)
        expected_price = 99000.0
        self.assertAlmostEqual(grid[0]["size_asset"], 1000.0 / expected_price, places=6)

    def test_size_capped_by_max_leverage(self):
        rm = _make_rm(tpsl_mode="pct", dca_max_orders=2, dca_step_pct=0.5,
                      dca_lot_multiplier=2.0, max_leverage=2.0)
        grid = rm.compute_dca_grid_plan(Signal.BUY, 1000, 150, 0, 100)
        self.assertLessEqual(grid[0]["size_usd"], 200.0)


class TestComputeDcaGridPlanAtr(unittest.TestCase):

    def test_buy_atr_layers(self):
        rm = _make_rm(tpsl_mode="atr", dca_max_orders=3, dca_step_atr_mult=1.5)
        grid = rm.compute_dca_grid_plan(Signal.BUY, 80000, 1000, 200, 10000)
        self.assertEqual(len(grid), 2)
        self.assertAlmostEqual(grid[0]["price"], 79700.0, places=1)
        self.assertAlmostEqual(grid[1]["price"], 79400.0, places=1)

    def test_sell_atr_layers(self):
        rm = _make_rm(tpsl_mode="atr", dca_max_orders=3, dca_step_atr_mult=2.0)
        grid = rm.compute_dca_grid_plan(Signal.SELL, 80000, 1000, 100, 10000)
        self.assertAlmostEqual(grid[0]["price"], 80200.0, places=1)
        self.assertAlmostEqual(grid[1]["price"], 80400.0, places=1)

    def test_zero_atr_returns_empty(self):
        rm = _make_rm(tpsl_mode="atr", dca_max_orders=3)
        self.assertEqual(rm.compute_dca_grid_plan(Signal.BUY, 80000, 1000, 0, 10000), [])


class TestExecutorPlaceDcaLimitGrid(unittest.TestCase):

    def _make_executor(self):
        from src.execution.executor import OrderExecutor
        client = MagicMock()
        client.round_size = MagicMock(side_effect=lambda sym, sz: round(sz, 3))
        notifier = MagicMock()
        return OrderExecutor(client, notifier), client

    def test_places_all_valid_orders(self):
        executor, client = self._make_executor()
        client.place_limit_order.return_value = {"orderId": 12345}
        grid = [
            {"layer": 2, "price": 79600.0, "size_usd": 1000.0, "size_asset": 0.0125},
            {"layer": 3, "price": 79202.0, "size_usd": 1000.0, "size_asset": 0.0126},
        ]
        placed = executor.place_dca_limit_grid("BTCUSDT", Signal.BUY, grid)
        self.assertEqual(len(placed), 2)
        self.assertTrue(all(p["status"] == "PLACED" for p in placed))
        self.assertEqual(client.place_limit_order.call_count, 2)

    def test_skips_below_min_notional(self):
        executor, client = self._make_executor()
        grid = [{"layer": 2, "price": 79600.0, "size_usd": 3.0, "size_asset": 0.00003}]
        placed = executor.place_dca_limit_grid("BTCUSDT", Signal.BUY, grid)
        self.assertEqual(len(placed), 0)
        client.place_limit_order.assert_not_called()

    def test_skips_zero_size_asset(self):
        executor, client = self._make_executor()
        grid = [{"layer": 2, "price": 79600.0, "size_usd": 1000.0, "size_asset": 0.0}]
        placed = executor.place_dca_limit_grid("BTCUSDT", Signal.BUY, grid)
        self.assertEqual(len(placed), 0)

    def test_failed_order_still_returned(self):
        executor, client = self._make_executor()
        client.place_limit_order.side_effect = Exception("API error")
        grid = [{"layer": 2, "price": 79600.0, "size_usd": 1000.0, "size_asset": 0.0125}]
        placed = executor.place_dca_limit_grid("BTCUSDT", Signal.SELL, grid)
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed[0]["status"], "FAILED")
        self.assertIsNone(placed[0]["orderId"])

    def test_sell_signal_uses_sell_side(self):
        executor, client = self._make_executor()
        client.place_limit_order.return_value = {"orderId": 99}
        grid = [{"layer": 2, "price": 80400.0, "size_usd": 1000.0, "size_asset": 0.0125}]
        executor.place_dca_limit_grid("BTCUSDT", Signal.SELL, grid)
        client.place_limit_order.assert_called_once_with("BTCUSDT", False, 0.013, 80400.0)


class TestClientLimitOrderMethods(unittest.TestCase):

    def _make_client(self):
        from src.config import Config
        from src.client import BinanceFuturesClient
        cfg = MagicMock(spec=Config)
        cfg.api_key = "test"
        cfg.api_secret = "test"
        cfg.api_url = "https://testnet.binancefuture.com"
        cfg.symbol = "BTCUSDT"
        client = BinanceFuturesClient(cfg)
        client._symbol_filters = {
            "BTCUSDT": {"tickSize": 0.1, "stepSize": 0.001, "minNotional": 5.0}
        }
        return client

    def test_get_open_limit_orders_filters_limit_type(self):
        client = self._make_client()
        fake_orders = [
            {"orderId": 1, "type": "LIMIT"},
            {"orderId": 2, "type": "STOP_MARKET"},
            {"orderId": 3, "type": "LIMIT"},
        ]
        client._request = MagicMock(return_value=fake_orders)
        result = client.get_open_limit_orders("BTCUSDT")
        self.assertEqual(len(result), 2)

    def test_cancel_all_open_orders_success(self):
        client = self._make_client()
        client._request = MagicMock(return_value={"code": 200})
        ok = client.cancel_all_open_orders("BTCUSDT")
        self.assertTrue(ok)
        client._request.assert_called_once_with(
            "DELETE", "/fapi/v1/allOpenOrders", {"symbol": "BTCUSDT"}, signed=True
        )

    def test_cancel_all_open_orders_fallback_on_exception(self):
        client = self._make_client()
        client._request = MagicMock(side_effect=Exception("timeout"))
        client.get_open_limit_orders = MagicMock(return_value=[])
        ok = client.cancel_all_open_orders("BTCUSDT")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
