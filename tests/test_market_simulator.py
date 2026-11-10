
"""
ChronosMatch Market Simulator and IPC Test Suite.

Tests:
- Market simulator order production
- Order generation and binary serialization
- Ring-buffer integration
- Backpressure and dropped-order behavior
- Sustained batch producer-consumer reliability
"""

import asyncio
import unittest
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import (
    Order,
    Side,
    pack_order,
    unpack_order,
    ORDER_SIZE,
)
from ipc.ring_buffer import RingBuffer
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig
from simulator.market_simulator import MarketSimulator, run_simulator


def test_produce_writes_orders():
    with RingBuffer(capacity=2, slot_size=ORDER_SIZE) as ring:
        simulator = MarketSimulator(ring, seed=42)

        assert asyncio.run(simulator.produce(2)) == 2

        orders = [unpack_order(ring.read()) for _ in range(2)]
        assert [order.order_id for order in orders] == [1, 2]
        assert all(order.side in (Side.BUY, Side.SELL) for order in orders)


def test_nonblocking_produce_does_not_consume_order_id_when_full():
    with RingBuffer(capacity=1, slot_size=ORDER_SIZE) as ring:
        simulator = MarketSimulator(ring, start_order_id=7, seed=42)
        assert ring.write(simulator.make_order())

        assert asyncio.run(
            simulator.produce(1, wait_when_full=False)
        ) == 0

        ring.read()
        assert asyncio.run(simulator.produce(1, wait_when_full=False)) == 1

        order = ring.read()
        assert order is not None
        assert unpack_order(order).order_id == 8


class TestOrderGenerator(unittest.TestCase):
    """Unit tests for synthetic order generation."""

    def test_buy_generation(self):
        config = OrderGeneratorConfig(
            total_orders=100, buy_ratio=1.0, seed=42
        )
        generator = OrderGenerator(config)
        orders = generator.generate_batch(100)

        self.assertEqual(len(orders), 100)

        for order in orders:
            self.assertEqual(order.side, Side.BUY)
            self.assertEqual(order.side_name, "BUY")
            self.assertGreater(order.price, 0)
            self.assertGreater(order.quantity, 0)

    def test_sell_generation(self):
        config = OrderGeneratorConfig(
            total_orders=100, buy_ratio=0.0, seed=42
        )
        generator = OrderGenerator(config)
        orders = generator.generate_batch(100)

        self.assertEqual(len(orders), 100)

        for order in orders:
            self.assertEqual(order.side, Side.SELL)
            self.assertEqual(order.side_name, "SELL")
            self.assertGreater(order.price, 0)
            self.assertGreater(order.quantity, 0)

    def test_unique_ids(self):
        initial_id = 5000
        count = 10_000

        config = OrderGeneratorConfig(
            initial_order_id=initial_id,
            total_orders=count,
            seed=42,
        )
        generator = OrderGenerator(config)
        orders = generator.generate_batch(count)

        self.assertEqual(len(orders), count)

        order_ids = [order.order_id for order in orders]

        self.assertEqual(len(set(order_ids)), count)

        for i, order_id in enumerate(order_ids):
            self.assertEqual(order_id, initial_id + i)

    def test_configurable_quantity(self):
        min_q = 15
        max_q = 45

        config = OrderGeneratorConfig(
            min_quantity=min_q,
            max_quantity=max_q,
            total_orders=1000,
            seed=123,
        )

        generator = OrderGenerator(config)
        orders = generator.generate_batch(1000)

        for order in orders:
            self.assertTrue(min_q <= order.quantity <= max_q)

    def test_configurable_price(self):
        min_p = 150.00
        max_p = 155.00

        config = OrderGeneratorConfig(
            min_price=min_p,
            max_price=max_p,
            total_orders=1000,
            seed=999,
        )

        generator = OrderGenerator(config)
        orders = generator.generate_batch(1000)

        for order in orders:
            self.assertTrue(min_p <= order.price <= max_p)

    def test_configurable_total_order_count(self):
        target_count = 250

        config = OrderGeneratorConfig(
            total_orders=target_count,
            seed=42,
        )

        generator = OrderGenerator(config)
        generated = list(generator)

        self.assertEqual(len(generated), target_count)
        self.assertEqual(generator.generated_count, target_count)
        self.assertFalse(generator.has_next())

        with self.assertRaises(StopIteration):
            generator.generate_order()

    def test_deterministic_generation_with_seed(self):
        seed = 424242

        cfg1 = OrderGeneratorConfig(total_orders=200, seed=seed)
        cfg2 = OrderGeneratorConfig(total_orders=200, seed=seed)

        gen1 = OrderGenerator(cfg1)
        gen2 = OrderGenerator(cfg2)

        batch1 = gen1.generate_batch(200)
        batch2 = gen2.generate_batch(200)

        self.assertEqual(len(batch1), len(batch2))

        for order1, order2 in zip(batch1, batch2):
            self.assertEqual(order1.order_id, order2.order_id)
            self.assertEqual(order1.side, order2.side)
            self.assertAlmostEqual(order1.price, order2.price, places=4)
            self.assertEqual(order1.quantity, order2.quantity)

    def test_binary_pack_unpack_roundtrip(self):
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
    """Integration tests for MarketSimulator and RingBuffer."""

    def test_successful_writes_to_ring_buffer(self):
        async def _test():
            rb = RingBuffer(capacity=500, slot_size=ORDER_SIZE)

            try:
                stats = await run_simulator(
                    ring_buffer=rb,
                    total_orders=300,
                    target_orders_per_sec=None,
                    seed=42,
                )

                self.assertEqual(stats.orders_generated, 300)
                self.assertEqual(stats.orders_written, 300)
                self.assertEqual(stats.orders_dropped, 0)
                self.assertEqual(stats.failed_writes, 0)
                self.assertEqual(rb.size(), 300)

                for i in range(300):
                    raw = rb.read()
                    self.assertIsNotNone(raw)

                    order = unpack_order(raw)
                    self.assertEqual(order.order_id, 1001 + i)

                self.assertTrue(rb.is_empty())

            finally:
                rb.close()

        asyncio.run(_test())

    def test_ring_buffer_full_behavior_drop_mode(self):
        async def _test():
            capacity = 50
            total_orders = 150

            rb = RingBuffer(
                capacity=capacity,
                slot_size=ORDER_SIZE,
            )

            try:
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

            finally:
                rb.close()

        asyncio.run(_test())

    def test_no_silent_data_loss_in_correctness_mode(self):
        async def _test():
            capacity = 100
            total_orders = 500

            rb = RingBuffer(
                capacity=capacity,
                slot_size=ORDER_SIZE,
            )

            consumed_orders = []
            stop_event = asyncio.Event()

            async def consumer():
                while not stop_event.is_set():
                    data = rb.read()

                    if data is not None:
                        consumed_orders.append(unpack_order(data))
                    else:
                        await asyncio.sleep(0)

                while True:
                    data = rb.read()

                    if data is None:
                        break

                    consumed_orders.append(unpack_order(data))

            consumer_task = asyncio.create_task(consumer())

            try:
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

                self.assertEqual(stats.orders_generated, total_orders)
                self.assertEqual(stats.orders_written, total_orders)
                self.assertEqual(stats.orders_dropped, 0)
                self.assertEqual(stats.failed_writes, 0)
                self.assertEqual(len(consumed_orders), total_orders)

                for i, order in enumerate(consumed_orders):
                    self.assertEqual(order.order_id, 1001 + i)

            finally:
                stop_event.set()
                await consumer_task
                rb.close()

        asyncio.run(_test())


def test_sustained_batch_producer_consumer_no_data_loss():
    """Verify 50,000 orders transfer without loss or reordering."""

    async def _test():
        total_orders = 50_000
        batch_size = 64

        with RingBuffer(capacity=256, slot_size=ORDER_SIZE) as ring:
            produced = 0
            consumed_ids = []

            async def producer():
                nonlocal produced

                while produced < total_orders:
                    end_id = min(
                        produced + batch_size,
                        total_orders,
                    )

                    batch = [
                        pack_order(
                            Order(
                                order_id=order_id,
                                price=100.0,
                                quantity=10,
                                side=Side.BUY,
                            )
                        )
                        for order_id in range(
                            produced + 1,
                            end_id + 1,
                        )
                    ]

                    written = ring.write_many(batch)
                    produced += written

                    if written == 0:
                        await asyncio.sleep(0)
                    elif produced % 1024 == 0:
                        await asyncio.sleep(0)

            async def consumer():
                while len(consumed_ids) < total_orders:
                    records = ring.read_many(batch_size)

                    if not records:
                        await asyncio.sleep(0)
                        continue

                    for record in records:
                        order = unpack_order(record)
                        consumed_ids.append(order.order_id)

            await asyncio.wait_for(
                asyncio.gather(producer(), consumer()),
                timeout=30,
            )

            assert produced == total_orders
            assert len(consumed_ids) == total_orders
            assert consumed_ids == list(range(1, total_orders + 1))
            assert ring.is_empty()

    asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
