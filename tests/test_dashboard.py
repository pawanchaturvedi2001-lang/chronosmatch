"""
Unit and integration tests for ChronosMatch Terminal Dashboard and Latency Metrics.
"""

import unittest
import asyncio
from unittest.mock import MagicMock, patch

from ipc.structures import Order, Side, ORDER_SIZE
from ipc.ring_buffer import RingBuffer
from core.order_book import LimitOrderBook, PyLimitOrderBook, IS_NATIVE_CYTHON
from core.models import Trade, PriceLevel
from core.engine import ChronosEngine
from monitoring.dashboard import OrderBookDashboard, safe_addstr, HAVE_CURSES


class TestDashboardAndMetrics(unittest.TestCase):
    """Test suite for terminal dashboard, safe curses rendering, and latency calculations."""

    def setUp(self):
        self.lob = LimitOrderBook()

    def test_safe_addstr_within_bounds(self):
        """Verify safe_addstr writes successfully when within screen bounds."""
        mock_stdscr = MagicMock()
        mock_stdscr.getmaxyx.return_value = (24, 80)

        safe_addstr(mock_stdscr, 5, 10, "Hello World", attr=0)
        mock_stdscr.addstr.assert_called_once_with(5, 10, "Hello World", 0)

    def test_safe_addstr_truncates_at_boundary(self):
        """Verify safe_addstr truncates text that exceeds horizontal boundary."""
        mock_stdscr = MagicMock()
        mock_stdscr.getmaxyx.return_value = (24, 80)

        # At x=75, available space is 80 - 75 - 1 = 4 chars
        safe_addstr(mock_stdscr, 5, 75, "Very Long Text", attr=0)
        mock_stdscr.addstr.assert_called_once_with(5, 75, "Very", 0)

    def test_safe_addstr_ignores_out_of_bounds(self):
        """Verify safe_addstr does not call addstr when y or x is out of bounds."""
        mock_stdscr = MagicMock()
        mock_stdscr.getmaxyx.return_value = (24, 80)

        safe_addstr(mock_stdscr, 25, 10, "Out of bounds y")
        mock_stdscr.addstr.assert_not_called()

        safe_addstr(mock_stdscr, 10, 85, "Out of bounds x")
        mock_stdscr.addstr.assert_not_called()

    def test_dashboard_empty_book_rendering(self):
        """Verify dashboard _draw_frame handles an empty limit order book without error."""
        dash = OrderBookDashboard(self.lob)
        mock_stdscr = MagicMock()
        mock_stdscr.getmaxyx.return_value = (30, 100)

        # Drawing frame on empty book should succeed without exceptions
        dash._draw_frame(mock_stdscr)
        self.assertTrue(mock_stdscr.erase.called)
        self.assertTrue(mock_stdscr.refresh.called)

    def test_dashboard_populated_book_and_trades(self):
        """Verify dashboard correctly formats populated book and trades."""
        # Populate orders
        self.lob.process_order(Order(order_id=1, price=100.0, quantity=50, side=Side.BUY, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=2, price=102.0, quantity=30, side=Side.SELL, timestamp_ns=2000))
        # Execute trade
        self.lob.process_order(Order(order_id=3, price=102.0, quantity=10, side=Side.BUY, timestamp_ns=3000))

        self.assertEqual(self.lob.total_trades_executed, 1)

        dash = OrderBookDashboard(self.lob)
        mock_stdscr = MagicMock()
        mock_stdscr.getmaxyx.return_value = (30, 100)

        dash._draw_frame(mock_stdscr)
        self.assertTrue(mock_stdscr.refresh.called)

    def test_dashboard_small_terminal_resizing_warning(self):
        """Verify dashboard displays resize warning when terminal is below 80x24."""
        dash = OrderBookDashboard(self.lob)
        mock_stdscr = MagicMock()
        mock_stdscr.getmaxyx.return_value = (20, 60)  # Too small

        dash._draw_frame(mock_stdscr)
        mock_stdscr.clear.assert_called_once()
        self.assertTrue(mock_stdscr.refresh.called)

    def test_engine_performance_stats_percentiles(self):
        """Verify ChronosEngine latency percentiles (Mean, P95, P99) are accurately calculated."""
        rb = RingBuffer(capacity=1024, slot_size=ORDER_SIZE)
        try:
            engine = ChronosEngine(ring_buffer=rb, lob=self.lob)

            # Insert known latencies: 1 to 100 microseconds
            for lat in range(1, 101):
                engine.match_latencies.append(float(lat))
                engine.e2e_latencies.append(float(lat * 2))

            stats = engine.get_performance_stats()

            # Mean of 1..100 = 50.5
            self.assertAlmostEqual(stats["match_latency_mean_us"], 50.5, places=1)
            # P95 of 1..100 = 96
            self.assertEqual(stats["match_latency_p95_us"], 96.0)
            # P99 of 1..100 = 100
            self.assertEqual(stats["match_latency_p99_us"], 100.0)

            # E2E mean of 2..200 = 101.0
            self.assertAlmostEqual(stats["e2e_latency_mean_us"], 101.0, places=1)
            self.assertEqual(stats["e2e_latency_p95_us"], 192.0)
            self.assertEqual(stats["e2e_latency_p99_us"], 200.0)
        finally:
            rb.close()

    def test_e2e_pipeline_with_engine_and_stats(self):
        """Verify end-to-end pipeline executes cleanly and produces populated stats."""
        rb = RingBuffer(capacity=4096, slot_size=ORDER_SIZE)
        try:
            engine = ChronosEngine(ring_buffer=rb, lob=self.lob, batch_size=100)
            results = asyncio.run(engine.start_pipeline(
                total_orders=1000,
                target_rate=0,
                with_dashboard=False,
                seed=123,
                auto_exit=True,
            ))

            self.assertEqual(results["orders_consumed"], 1000)
            self.assertEqual(results["dropped"], 0)
            self.assertGreater(results["consumer_throughput"], 0)
            self.assertGreaterEqual(results["match_latency_mean_us"], 0.0)
            self.assertGreaterEqual(results["e2e_latency_mean_us"], 0.0)
        finally:
            rb.close()


if __name__ == "__main__":
    unittest.main()
