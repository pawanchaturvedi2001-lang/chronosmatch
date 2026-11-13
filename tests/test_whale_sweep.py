"""
Unit and integration tests for ChronosMatch Whale Order Sweep Detection (Week 2).

Verifies:
1. Normal single-level matching is NOT labeled as a multi-level sweep.
2. Large order matching only one level is NOT labeled as a sweep.
3. Multi-level sweep: incoming BUY order sweeps multiple ASK price levels.
4. Multi-level sweep: incoming SELL order sweeps multiple BID price levels.
5. Partial execution: sweep leaves residual quantity resting in the book.
6. Full execution: sweep consumes all levels and order is completely filled.
7. Correct sweep event metadata: order_id, side, levels_swept, total_quantity, start/end price, trades_count.
8. Unmatched remaining quantity is correctly preserved.
9. Dashboard integration: dashboard renders whale sweep alert and clear states.
"""

import unittest
from unittest.mock import MagicMock
from collections import deque

from ipc.structures import Order, Side
from core.models import Trade, WhaleSweep
from core.order_book import LimitOrderBook, PyLimitOrderBook
from monitoring.dashboard import OrderBookDashboard


class TestWhaleSweepDetection(unittest.TestCase):
    """Test suite verifying detection and reporting of multi-level liquidity sweeps."""

    def setUp(self):
        self.lob = LimitOrderBook(tick_size=0.01)

    def test_normal_single_level_matching_not_a_sweep(self):
        """1. Verify that single-level matches are NOT labeled as whale sweeps."""
        # Resting sell
        self.lob.process_order(Order(order_id=1, price=100.0, quantity=50, side=Side.SELL, timestamp_ns=1000))
        # Incoming buy at matching price
        trades = self.lob.process_order(Order(order_id=2, price=100.0, quantity=50, side=Side.BUY, timestamp_ns=2000))

        self.assertEqual(len(trades), 1)
        self.assertEqual(self.lob.total_sweeps_detected, 0)
        self.assertIsNone(self.lob.last_sweep)
        self.assertEqual(len(self.lob.get_recent_sweeps()), 0)

    def test_large_order_single_level_not_a_sweep(self):
        """2. Verify that a large quantity order matching only one price level is NOT a sweep."""
        # 10,000 shares at a single price level
        self.lob.process_order(Order(order_id=10, price=105.0, quantity=10_000, side=Side.SELL, timestamp_ns=1000))
        trades = self.lob.process_order(Order(order_id=11, price=105.0, quantity=10_000, side=Side.BUY, timestamp_ns=2000))

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 10_000)
        # Even though volume is 10,000, it only touched 1 price level, so it is NOT a multi-level sweep
        self.assertEqual(self.lob.total_sweeps_detected, 0)
        self.assertIsNone(self.lob.last_sweep)

    def test_buy_multi_level_sweep_full_fill(self):
        """3. Incoming BUY sweeps 3 ASK price levels with complete fill."""
        # Setup 3 ask levels:
        # Ask 1: 100 @ 101.00
        # Ask 2: 150 @ 102.00
        # Ask 3: 200 @ 103.00
        self.lob.process_order(Order(order_id=101, price=101.00, quantity=100, side=Side.SELL, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=102, price=102.00, quantity=150, side=Side.SELL, timestamp_ns=2000))
        self.lob.process_order(Order(order_id=103, price=103.00, quantity=200, side=Side.SELL, timestamp_ns=3000))

        self.assertEqual(len(self.lob.get_depth(levels=5)[1]), 3)

        # Whale BUY order: 450 shares @ 103.00 (exactly sweeps all 3 levels)
        whale_order = Order(order_id=999, price=103.00, quantity=450, side=Side.BUY, timestamp_ns=4000)
        trades = self.lob.process_order(whale_order)

        self.assertEqual(len(trades), 3)
        self.assertEqual(self.lob.total_sweeps_detected, 1)

        sweep = self.lob.last_sweep
        self.assertIsNotNone(sweep)
        self.assertEqual(sweep.order_id, 999)
        self.assertEqual(sweep.side, "BUY")
        self.assertEqual(sweep.levels_swept, 3)
        self.assertEqual(sweep.total_quantity, 450)
        self.assertAlmostEqual(sweep.start_price, 101.00, places=2)
        self.assertAlmostEqual(sweep.end_price, 103.00, places=2)
        self.assertEqual(sweep.trades_count, 3)
        self.assertEqual(sweep.residual_quantity, 0)  # Full fill
        self.assertEqual(len(sweep.trades), 3)

        # Book should now be empty of asks up to 103
        self.assertIsNone(self.lob.get_best_ask())

    def test_sell_multi_level_sweep_partial_fill_residual(self):
        """4. Incoming SELL sweeps 2 BID price levels with residual resting in book."""
        # Setup 2 bid levels:
        # Bid 1: 200 @ 100.00
        # Bid 2: 100 @ 99.00
        self.lob.process_order(Order(order_id=201, price=100.00, quantity=200, side=Side.BUY, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=202, price=99.00, quantity=100, side=Side.BUY, timestamp_ns=2000))

        # Whale SELL order: 500 shares @ 98.00 (eats 200 @ 100.00, 100 @ 99.00, and 200 rests @ 98.00)
        whale_sell = Order(order_id=888, price=98.00, quantity=500, side=Side.SELL, timestamp_ns=3000)
        trades = self.lob.process_order(whale_sell)

        self.assertEqual(len(trades), 2)
        self.assertEqual(self.lob.total_sweeps_detected, 1)

        sweep = self.lob.last_sweep
        self.assertIsNotNone(sweep)
        self.assertEqual(sweep.order_id, 888)
        self.assertEqual(sweep.side, "SELL")
        self.assertEqual(sweep.levels_swept, 2)
        self.assertEqual(sweep.total_quantity, 300)
        self.assertAlmostEqual(sweep.start_price, 100.00, places=2)
        self.assertAlmostEqual(sweep.end_price, 99.00, places=2)
        self.assertEqual(sweep.trades_count, 2)
        self.assertEqual(sweep.residual_quantity, 200)  # 500 - 300 = 200 remaining

        # Best ask should now be the residual 200 @ 98.00
        best_ask = self.lob.get_best_ask()
        self.assertIsNotNone(best_ask)
        self.assertAlmostEqual(best_ask[0], 98.00, places=2)
        self.assertEqual(best_ask[1], 200)

    def test_whale_sweep_summary_and_dict(self):
        """5. Verify WhaleSweep data conversions and summary strings."""
        t1 = Trade(trade_id=1, price=10.0, quantity=50, buy_order_id=10, sell_order_id=1, timestamp_ns=100)
        t2 = Trade(trade_id=2, price=11.0, quantity=50, buy_order_id=10, sell_order_id=2, timestamp_ns=200)

        sweep = WhaleSweep(
            order_id=10,
            side="BUY",
            levels_swept=2,
            total_quantity=100,
            start_price=10.0,
            end_price=11.0,
            trades_count=2,
            trades=[t1, t2],
            residual_quantity=25,
            timestamp_ns=100,
        )

        d = sweep.to_dict()
        self.assertEqual(d["order_id"], 10)
        self.assertEqual(d["levels_swept"], 2)
        self.assertEqual(d["total_quantity"], 100)
        self.assertEqual(d["residual_quantity"], 25)
        self.assertEqual(len(d["trades"]), 2)

        summary = sweep.summary_str()
        self.assertIn("WHALE SWEEP #10", summary)
        self.assertIn("2 levels swept", summary)
        self.assertIn("rest: 25", summary)

    def test_dashboard_renders_whale_sweep_notification(self):
        """6. Verify dashboard displays whale sweep alert when last_sweep is present."""
        # Cause a 2-level sweep
        self.lob.process_order(Order(order_id=1, price=50.0, quantity=10, side=Side.SELL, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=2, price=51.0, quantity=10, side=Side.SELL, timestamp_ns=2000))
        self.lob.process_order(Order(order_id=3, price=52.0, quantity=20, side=Side.BUY, timestamp_ns=3000))

        dash = OrderBookDashboard(self.lob)
        mock_stdscr = MagicMock()
        mock_stdscr.getmaxyx.return_value = (30, 100)

        dash._draw_frame(mock_stdscr)
        self.assertTrue(mock_stdscr.refresh.called)

        # Inspect addstr calls to verify WHALE SWEEP ALERT was written
        calls = [c[0][2] for c in mock_stdscr.addstr.call_args_list if len(c[0]) > 2]
        found_alert = any("WHALE SWEEP ALERT" in str(msg) for msg in calls)
        self.assertTrue(found_alert, "Expected 'WHALE SWEEP ALERT' to be rendered on dashboard frame")


if __name__ == "__main__":
    unittest.main()
