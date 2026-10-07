"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
Market Simulator Unit and Integration Test Suite (Member 3)

Tests:
- BUY order generation
- SELL order generation
- Unique order IDs
- Configurable quantity ranges
- Configurable price ranges
- Configurable total order count
- Deterministic order generation with random seed
- Binary packing and unpacking roundtrip
- Successful writes to IPC RingBuffer
- Ring buffer full behavior under drop mode
- Lossless backpressure with zero silent data loss in correctness mode
"""

import asyncio
import unittest
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import Order, Side, pack_order, unpack_order, ORDER_SIZE
from ipc.ring_buffer import RingBuffer
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig
from simulator.market_simulator import MarketSimulator, run_simulator


class TestOrderGenerator(unittest.TestCase):
    """Unit tests for synthetic order generation logic."""

    def test_buy_generation(self):
        """Verify generator correctly produces BUY orders with side == Side.BUY."""
        config = OrderGeneratorConfig(total_orders=100, buy_ratio=1.0, seed=42)
        generator = OrderGenerator(config)
        orders = generator.generate_batch(100)

        self.assertEqual(len(orders), 100)
        for order in orders:
            self.assertEqual(order.side, Side.BUY)
            self.assertEqual(order.side_name, "BUY")
            self.assertGreater(order.price, 0)
            self.assertGreater(order.quantity, 0)

    def test_sell_generation(self):
        """Verify generator correctly produces SELL orders with side == Side.SELL."""
        config = OrderGeneratorConfig(total_orders=100, buy_ratio=0.0, seed=42)
        generator = OrderGenerator(config)
        orders = generator.generate_batch(100)

        self.assertEqual(len(orders), 100)
        for order in orders:
            self.assertEqual(order.side, Side.SELL)
            self.assertEqual(order.side_name, "SELL")
            self.assertGreater(order.price, 0)
            self.assertGreater(order.quantity, 0)

    def test_unique_ids(self):
        """Verify that all generated orders have unique, strictly increasing IDs."""
        initial_id = 5000
        count = 10_000
        config = OrderGeneratorConfig(initial_order_id=initial_id, total_orders=count, seed=42)
        generator = OrderGenerator(config)
        orders = generator.generate_batch(count)

        self.assertEqual(len(orders), count)
        order_ids = [o.order_id for o in orders]
        unique_ids = set(order_ids)

        self.assertEqual(len(unique_ids), count, "Order IDs must be strictly unique")
        # Check monotonic increment
        for i, order_id in enumerate(order_ids):
            self.assertEqual(order_id, initial_id + i)

    def test_configurable_quantity(self):
        """Verify generated quantities adhere strictly to [min_quantity, max_quantity]."""
        min_q = 15
        max_q = 45
        config = OrderGeneratorConfig(
            min_quantity=min_q, max_quantity=max_q, total_orders=1000, seed=123
        )
        generator = OrderGenerator(config)
        orders = generator.generate_batch(1000)

        for o in orders:
            self.assertTrue(
                min_q <= o.quantity <= max_q,
                f"Quantity {o.quantity} out of bounds [{min_q}, {max_q}]",
            )

    def test_configurable_price(self):
        """Verify generated prices adhere strictly to [min_price, max_price]."""
        min_p = 150.00
        max_p = 155.00
        config = OrderGeneratorConfig(
            min_price=min_p, max_price=max_p, total_orders=1000, seed=999
        )
        generator = OrderGenerator(config)
        orders = generator.generate_batch(1000)

        for o in orders:
            self.assertTrue(
                min_p <= o.price <= max_p,
                f"Price {o.price} out of bounds [{min_p}, {max_p}]",
            )

    def test_configurable_total_order_count(self):
        """Verify generator stops exactly when total_orders limit is reached."""
        target_count = 250
        config = OrderGeneratorConfig(total_orders=target_count, seed=42)
        generator = OrderGenerator(config)

        generated = list(generator)
        self.assertEqual(len(generated), target_count)
        self.assertEqual(generator.generated_count, target_count)
        self.assertFalse(generator.has_next())

        with self.assertRaises(StopIteration):
            generator.generate_order()

    def test_deterministic_generation_with_seed(self):
        """Verify that identical random seeds produce identical sequences of orders."""
        seed = 424242
        cfg1 = OrderGeneratorConfig(total_orders=200, seed=seed)
        cfg2 = OrderGeneratorConfig(total_orders=200, seed=seed)

        gen1 = OrderGenerator(cfg1)
        gen2 = OrderGenerator(cfg2)

        batch1 = gen1.generate_batch(200)
        batch2 = gen2.generate_batch(200)

        self.assertEqual(len(batch1), len(batch2))
        for o1, o2 in zip(batch1, batch2):
            self.assertEqual(o1.order_id, o2.order_id)
            self.assertEqual(o1.side, o2.side)
            self.assertAlmostEqual(o1.price, o2.price, places=4)
            self.assertEqual(o1.quantity, o2.quantity)

    def test_binary_pack_unpack_roundtrip(self):
        """Verify pack_order and unpack_order preserve binary fidelity."""
        order = Order(
            order_id=987654321,
            price=123.45,
            quantity=500,
            side=Side.BUY,
            timestamp_ns=1700000000123456789,
        )
        data = pack_order(order)
        self.assertEqual(len(data), ORDER_SIZE)

        unpacked = unpack_order(data)
        self.assertEqual(order.order_id, unpacked.order_id)
        self.assertAlmostEqual(order.price, unpacked.price, places=4)
        self.assertEqual(order.quantity, unpacked.quantity)
        self.assertEqual(order.side, unpacked.side)
        self.assertEqual(order.timestamp_ns, unpacked.timestamp_ns)


class TestMarketSimulatorIntegration(unittest.TestCase):
    """Integration tests for MarketSimulator with RingBuffer and backpressure modes."""

    def test_successful_writes_to_ring_buffer(self):
        """Verify simulator successfully blasts orders and they are readable from the ring buffer."""
        async def _test():
            rb = RingBuffer(capacity=500, slot_size=ORDER_SIZE)
            stats = await run_simulator(
                ring_buffer=rb,
                total_orders=300,
                target_orders_per_sec=None,  # unthrottled
                seed=42,
            )

            self.assertEqual(stats.orders_generated, 300)
            self.assertEqual(stats.orders_written, 300)
            self.assertEqual(stats.orders_dropped, 0)
            self.assertEqual(stats.failed_writes, 0)
            self.assertEqual(rb.size(), 300)

            # Read all 300 orders back and verify integrity
            for i in range(300):
                raw = rb.read()
                self.assertIsNotNone(raw)
                order = unpack_order(raw)
                self.assertEqual(order.order_id, 1001 + i)

            self.assertTrue(rb.is_empty())
            rb.close()

        asyncio.run(_test())

    def test_ring_buffer_full_behavior_drop_mode(self):
        """Verify that in drop mode, writes to a full buffer increment dropped orders without hanging."""
        async def _test():
            capacity = 50
            total_orders = 150
            rb = RingBuffer(capacity=capacity, slot_size=ORDER_SIZE)

            stats = await run_simulator(
                ring_buffer=rb,
                total_orders=total_orders,
                target_orders_per_sec=None,
                backpressure_mode="drop",
                seed=42,
            )

            self.assertEqual(stats.orders_generated, total_orders)
            self.assertEqual(stats.orders_written, capacity)
            self.assertEqual(stats.orders_dropped, total_orders - capacity)
            self.assertEqual(stats.failed_writes, total_orders - capacity)
            self.assertEqual(rb.size(), capacity)
            self.assertTrue(rb.is_full())

            rb.close()

        asyncio.run(_test())

    def test_no_silent_data_loss_in_correctness_mode(self):
        """Verify that in wait mode, zero orders are lost when buffer fills, provided a consumer drains it."""
        async def _test():
            capacity = 100
            total_orders = 500
            rb = RingBuffer(capacity=capacity, slot_size=ORDER_SIZE)

            consumed_orders = []
            stop_event = asyncio.Event()

            async def consumer():
                while not stop_event.is_set():
                    data = rb.read()
                    if data is not None:
                        consumed_orders.append(unpack_order(data))
                    else:
                        await asyncio.sleep(0)
                # Final drain
                while True:
                    data = rb.read()
                    if data is None:
                        break
                    consumed_orders.append(unpack_order(data))

            consumer_task = asyncio.create_task(consumer())

            stats = await run_simulator(
                ring_buffer=rb,
                total_orders=total_orders,
                target_orders_per_sec=None,
                batch_size=20,
                backpressure_mode="wait",
                seed=42,
            )

            stop_event.set()
            await consumer_task

            # Verification of zero data loss
            self.assertEqual(stats.orders_generated, total_orders)
            self.assertEqual(stats.orders_written, total_orders)
            self.assertEqual(stats.orders_dropped, 0, "No orders should ever be dropped in wait mode")
            self.assertEqual(stats.failed_writes, 0)
            self.assertEqual(len(consumed_orders), total_orders)

            # Check that every single order ID was preserved sequentially
            for i, order in enumerate(consumed_orders):
                self.assertEqual(order.order_id, 1001 + i)

            rb.close()

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
