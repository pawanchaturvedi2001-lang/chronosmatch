"""
ChronosMatch Limit Order Book & Matching Engine Test Suite (Week 2)

Comprehensive deterministic tests for all matching scenarios:
1. Buy order matching sell order
2. Sell order matching buy order
3. No match when prices do not cross
4. Best-price priority
5. Time priority for orders at the same price
6. Partial execution of a larger order
7. One incoming order matching multiple resting orders
8. Multiple price levels being consumed
9. Correct residual quantity after partial fills
10. Removal of completely filled orders
11. Correct best bid, best ask, and spread
12. Trade records containing correct order IDs, prices, quantities, and timestamps
13. Empty order book behavior
14. Invalid order handling
15. Integration with existing Week 1 Order format and simulator
"""

import unittest
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import Order, Side
from core.models import Trade, PriceLevel
from core.order_book import LimitOrderBook, PyLimitOrderBook
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig


class TestLimitOrderBookCorrectness(unittest.TestCase):
    """Deterministic correctness test suite for Price-Time Priority matching."""

    def setUp(self):
        self.lob = LimitOrderBook(tick_size=0.01, self_trade_prevention=True)

    def test_buy_order_matching_sell_order(self):
        """1. A buy order matching a resting sell order."""
        sell_order = Order(order_id=101, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=1000)
        buy_order = Order(order_id=102, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=2000)

        trades1 = self.lob.process_order(sell_order)
        self.assertEqual(len(trades1), 0, "First order should rest in book")
        self.assertEqual(self.lob.get_best_ask(), (100.00, 10))

        trades2 = self.lob.process_order(buy_order)
        self.assertEqual(len(trades2), 1)
        t = trades2[0]
        self.assertEqual(t.price, 100.00)
        self.assertEqual(t.quantity, 10)
        self.assertEqual(t.buy_order_id, 102)
        self.assertEqual(t.sell_order_id, 101)
        self.assertIsNone(self.lob.get_best_ask(), "Book should be empty after fill")
        self.assertIsNone(self.lob.get_best_bid(), "Book should be empty after fill")

    def test_sell_order_matching_buy_order(self):
        """2. A sell order matching a resting buy order."""
        buy_order = Order(order_id=201, price=105.00, quantity=15, side=Side.BUY, timestamp_ns=1000)
        sell_order = Order(order_id=202, price=105.00, quantity=15, side=Side.SELL, timestamp_ns=2000)

        self.lob.process_order(buy_order)
        self.assertEqual(self.lob.get_best_bid(), (105.00, 15))

        trades = self.lob.process_order(sell_order)
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual(t.price, 105.00)
        self.assertEqual(t.quantity, 15)
        self.assertEqual(t.buy_order_id, 201)
        self.assertEqual(t.sell_order_id, 202)
        self.assertIsNone(self.lob.get_best_bid())

    def test_no_match_when_prices_do_not_cross(self):
        """3. No match when prices do not cross (bid < ask)."""
        buy_order = Order(order_id=301, price=99.00, quantity=10, side=Side.BUY, timestamp_ns=1000)
        sell_order = Order(order_id=302, price=101.00, quantity=10, side=Side.SELL, timestamp_ns=2000)

        trades_b = self.lob.process_order(buy_order)
        trades_s = self.lob.process_order(sell_order)

        self.assertEqual(len(trades_b), 0)
        self.assertEqual(len(trades_s), 0)
        self.assertEqual(self.lob.get_best_bid(), (99.00, 10))
        self.assertEqual(self.lob.get_best_ask(), (101.00, 10))
        self.assertEqual(self.lob.get_spread(), 2.00)

    def test_best_price_priority(self):
        """4. Best-price priority: Buy order matches lowest available sell price."""
        sell_high = Order(order_id=401, price=102.00, quantity=10, side=Side.SELL, timestamp_ns=1000)
        sell_low = Order(order_id=402, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=2000)
        self.lob.process_order(sell_high)
        self.lob.process_order(sell_low)

        # Incoming BUY with limit 103.00: must match sell_low (100.00), NOT sell_high
        incoming_buy = Order(order_id=403, price=103.00, quantity=10, side=Side.BUY, timestamp_ns=3000)
        trades = self.lob.process_order(incoming_buy)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].sell_order_id, 402, "Must match lowest price first")
        self.assertEqual(trades[0].price, 100.00, "Execution price is set by resting order")
        self.assertEqual(self.lob.get_best_ask(), (102.00, 10), "Higher sell order must remain resting")

    def test_time_priority_at_same_price(self):
        """5. Time priority for orders at the same price (earlier eligible order matches first)."""
        sell_first = Order(order_id=501, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=1000)
        sell_second = Order(order_id=502, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=2000)
        self.lob.process_order(sell_first)
        self.lob.process_order(sell_second)

        incoming_buy = Order(order_id=503, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=3000)
        trades = self.lob.process_order(incoming_buy)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].sell_order_id, 501, "Must match earliest resting order first")
        # Remaining ask must be sell_second
        self.assertEqual(self.lob.get_best_ask(), (100.00, 10))

    def test_partial_execution_of_larger_order(self):
        """6. Partial execution of a larger resting order."""
        resting_sell = Order(order_id=601, price=100.00, quantity=25, side=Side.SELL, timestamp_ns=1000)
        self.lob.process_order(resting_sell)

        incoming_buy = Order(order_id=602, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=2000)
        trades = self.lob.process_order(incoming_buy)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 10)
        # 15 shares should remain on the sell side
        self.assertEqual(self.lob.get_best_ask(), (100.00, 15))

    def test_one_incoming_order_matching_multiple_resting_orders(self):
        """7. One incoming order matching multiple resting orders at same price."""
        self.lob.process_order(Order(order_id=701, price=100.00, quantity=5, side=Side.SELL, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=702, price=100.00, quantity=7, side=Side.SELL, timestamp_ns=2000))

        # Incoming BUY for 10 shares: consumes 701 (5 shares) and partially fills 702 (5 shares)
        incoming_buy = Order(order_id=703, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=3000)
        trades = self.lob.process_order(incoming_buy)

        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].sell_order_id, 701)
        self.assertEqual(trades[0].quantity, 5)
        self.assertEqual(trades[1].sell_order_id, 702)
        self.assertEqual(trades[1].quantity, 5)
        # Remaining on order 702: 7 - 5 = 2 shares
        self.assertEqual(self.lob.get_best_ask(), (100.00, 2))

    def test_multiple_price_levels_consumed(self):
        """8. Multiple price levels being consumed by a large order."""
        self.lob.process_order(Order(order_id=801, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=802, price=101.00, quantity=10, side=Side.SELL, timestamp_ns=2000))
        self.lob.process_order(Order(order_id=803, price=102.00, quantity=10, side=Side.SELL, timestamp_ns=3000))

        # Incoming BUY for 25 shares @ 102.50
        incoming_buy = Order(order_id=804, price=102.50, quantity=25, side=Side.BUY, timestamp_ns=4000)
        trades = self.lob.process_order(incoming_buy)

        self.assertEqual(len(trades), 3)
        self.assertEqual(trades[0].price, 100.00)
        self.assertEqual(trades[0].quantity, 10)
        self.assertEqual(trades[1].price, 101.00)
        self.assertEqual(trades[1].quantity, 10)
        self.assertEqual(trades[2].price, 102.00)
        self.assertEqual(trades[2].quantity, 5)
        # Remaining on level 102.00: 5 shares
        self.assertEqual(self.lob.get_best_ask(), (102.00, 5))

    def test_correct_residual_quantity_after_partial_fills(self):
        """9. Correct residual quantity placed on book after partial fills of incoming order."""
        self.lob.process_order(Order(order_id=901, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=1000))

        # Incoming BUY for 25 shares @ 100.00: fills 10, leaves 15 resting as BID
        incoming_buy = Order(order_id=902, price=100.00, quantity=25, side=Side.BUY, timestamp_ns=2000)
        trades = self.lob.process_order(incoming_buy)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 10)
        self.assertIsNone(self.lob.get_best_ask(), "Sell side must be exhausted")
        self.assertEqual(self.lob.get_best_bid(), (100.00, 15), "Residual 15 shares must rest on bid side")

    def test_removal_of_completely_filled_orders(self):
        """10. Removal of completely filled orders from book index."""
        self.lob.process_order(Order(order_id=1001, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=1002, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=2000))

        # Order 1001 is completely filled; trying to cancel it should return False
        cancelled = self.lob.cancel_order(1001)
        self.assertFalse(cancelled, "Filled order cannot be cancelled")

    def test_correct_best_bid_best_ask_and_spread(self):
        """11. Correct best bid, best ask, and spread calculation."""
        self.lob.process_order(Order(order_id=1101, price=99.50, quantity=20, side=Side.BUY, timestamp_ns=1000))
        self.lob.process_order(Order(order_id=1102, price=99.00, quantity=30, side=Side.BUY, timestamp_ns=1001))
        self.lob.process_order(Order(order_id=1103, price=100.50, quantity=15, side=Side.SELL, timestamp_ns=1002))
        self.lob.process_order(Order(order_id=1104, price=101.00, quantity=25, side=Side.SELL, timestamp_ns=1003))

        self.assertEqual(self.lob.get_best_bid(), (99.50, 20))
        self.assertEqual(self.lob.get_best_ask(), (100.50, 15))
        self.assertAlmostEqual(self.lob.get_spread(), 1.00, places=4)

        # Check market depth
        bids_depth, asks_depth = self.lob.get_depth(levels=5)
        self.assertEqual(len(bids_depth), 2)
        self.assertEqual(bids_depth[0].price, 99.50)
        self.assertEqual(bids_depth[0].total_quantity, 20)
        self.assertEqual(bids_depth[1].price, 99.00)
        self.assertEqual(bids_depth[1].total_quantity, 30)

        self.assertEqual(len(asks_depth), 2)
        self.assertEqual(asks_depth[0].price, 100.50)
        self.assertEqual(asks_depth[0].total_quantity, 15)
        self.assertEqual(asks_depth[1].price, 101.00)
        self.assertEqual(asks_depth[1].total_quantity, 25)

    def test_trade_records_integrity(self):
        """12. Trade records containing correct order IDs, prices, quantities, and timestamps."""
        t_before = 1000
        self.lob.process_order(Order(order_id=1201, price=50.25, quantity=100, side=Side.SELL, timestamp_ns=t_before))
        trades = self.lob.process_order(Order(order_id=1202, price=50.30, quantity=40, side=Side.BUY, timestamp_ns=2000))

        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertGreater(t.trade_id, 0)
        self.assertEqual(t.price, 50.25)
        self.assertEqual(t.quantity, 40)
        self.assertEqual(t.buy_order_id, 1202)
        self.assertEqual(t.sell_order_id, 1201)
        self.assertGreater(t.timestamp_ns, 0)

        recent = self.lob.get_recent_trades(limit=5)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].trade_id, t.trade_id)

    def test_empty_order_book_behavior(self):
        """13. Empty order book behavior."""
        self.assertIsNone(self.lob.get_best_bid())
        self.assertIsNone(self.lob.get_best_ask())
        self.assertIsNone(self.lob.get_spread())
        self.assertEqual(self.lob.get_depth(levels=5), ([], []))
        self.assertFalse(self.lob.cancel_order(99999))
        self.assertEqual(len(self.lob.get_recent_trades()), 0)

    def test_invalid_order_handling(self):
        """14. Invalid order handling (e.g., non-positive quantity)."""
        invalid_order = Order(order_id=1401, price=100.00, quantity=0, side=Side.BUY, timestamp_ns=1000)
        trades = self.lob.process_order(invalid_order)
        self.assertEqual(len(trades), 0)
        self.assertIsNone(self.lob.get_best_bid())

    def test_integration_with_simulator_and_order_format(self):
        """15. Integration with existing Week 1 Order format and simulator generator."""
        config = OrderGeneratorConfig(
            initial_order_id=10001,
            total_orders=200,
            min_price=98.00,
            max_price=102.00,
            buy_ratio=0.50,
            seed=42
        )
        generator = OrderGenerator(config)

        total_trades = 0
        for order in generator:
            trades = self.lob.process_order(order)
            total_trades += len(trades)

        self.assertEqual(self.lob.total_orders_processed, 200)
        self.assertEqual(self.lob.total_trades_executed, total_trades)
        self.assertGreater(total_trades, 0, "Realistic overlapping random stream should produce trades")


if __name__ == "__main__":
    unittest.main()

