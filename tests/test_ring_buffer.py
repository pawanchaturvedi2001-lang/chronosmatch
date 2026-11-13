"""
Unit and integration tests for ChronosMatch IPC RingBuffer.

Verifies:
1. Writing and reading one order.
2. Writing and reading multiple orders.
3. Circular wraparound beyond buffer capacity.
4. Full buffer handling (rejects writes when full).
5. Empty buffer handling (returns None when empty).
6. Producer and consumer operating concurrently without race conditions.
7. Separate-process IPC communication via file-backed mmap.
8. Zero missing orders under concurrent load.
9. Zero duplicate orders.
10. Zero corrupted order records (byte fidelity check).
11. Strict FIFO ordering preservation.
"""

import os
import tempfile
import threading
import time
import unittest
from multiprocessing import Process, Queue
from typing import List

from ipc.structures import Order, Side, pack_order, unpack_order, ORDER_SIZE
from ipc.ring_buffer import RingBuffer


def _proc_producer(filepath: str, order_count: int, err_queue: Queue):
    """Producer function executed in a separate process."""
    try:
        rb = RingBuffer(capacity=128, filepath=filepath, create=False)
        for i in range(order_count):
            order = Order(
                order_id=10_000 + i,
                price=100.0 + (i % 50) * 0.1,
                quantity=10 + (i % 20),
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                timestamp_ns=1_000_000_000 + i,
            )
            payload = pack_order(order)
            # Spin until slot is available (lossless producer)
            while not rb.write(payload):
                time.sleep(0.0001)
        rb.close()
    except Exception as exc:
        err_queue.put(f"Producer exception: {exc}")


def _proc_consumer(filepath: str, order_count: int, result_queue: Queue, err_queue: Queue):
    """Consumer function executed in a separate process."""
    try:
        rb = RingBuffer(capacity=128, filepath=filepath, create=False)
        received_ids = []
        while len(received_ids) < order_count:
            raw = rb.read()
            if raw is not None:
                order = unpack_order(raw)
                received_ids.append(order.order_id)
            else:
                time.sleep(0.0001)
        rb.close()
        result_queue.put(received_ids)
    except Exception as exc:
        err_queue.put(f"Consumer exception: {exc}")


class TestRingBufferRaceFree(unittest.TestCase):
    """Complete test suite for SPSC RingBuffer operations and concurrency."""

    def test_single_order_write_read(self):
        """1. Writing and reading one order."""
        rb = RingBuffer(capacity=16, slot_size=ORDER_SIZE)
        try:
            self.assertTrue(rb.is_empty())
            self.assertEqual(rb.size(), 0)

            order = Order(order_id=101, price=99.50, quantity=10, side=Side.BUY, timestamp_ns=123456789)
            written = rb.write(pack_order(order))
            self.assertTrue(written)
            self.assertEqual(rb.size(), 1)
            self.assertFalse(rb.is_empty())

            raw = rb.read()
            self.assertIsNotNone(raw)
            unpacked = unpack_order(raw)
            self.assertEqual(unpacked.order_id, 101)
            self.assertAlmostEqual(unpacked.price, 99.50, places=2)
            self.assertEqual(unpacked.quantity, 10)
            self.assertEqual(unpacked.side, Side.BUY)
            self.assertEqual(unpacked.timestamp_ns, 123456789)
            self.assertTrue(rb.is_empty())
        finally:
            rb.close()

    def test_multiple_orders_write_read(self):
        """2. Writing and reading multiple orders."""
        capacity = 32
        count = 20
        rb = RingBuffer(capacity=capacity, slot_size=ORDER_SIZE)
        try:
            for i in range(count):
                order = Order(order_id=200 + i, price=100.0 + i, quantity=5 + i, side=Side.SELL)
                self.assertTrue(rb.write(pack_order(order)))

            self.assertEqual(rb.size(), count)

            for i in range(count):
                raw = rb.read()
                self.assertIsNotNone(raw)
                order = unpack_order(raw)
                self.assertEqual(order.order_id, 200 + i)
                self.assertAlmostEqual(order.price, 100.0 + i, places=2)
                self.assertEqual(order.quantity, 5 + i)

            self.assertTrue(rb.is_empty())
        finally:
            rb.close()

    def test_circular_wraparound(self):
        """3. Circular wraparound beyond buffer capacity."""
        capacity = 8
        total_cycles = 50  # Write and read 50 orders in a capacity-8 buffer
        rb = RingBuffer(capacity=capacity, slot_size=ORDER_SIZE)
        try:
            for i in range(total_cycles):
                order = Order(order_id=300 + i, price=150.0 + (i % 10), quantity=10, side=Side.BUY)
                self.assertTrue(rb.write(pack_order(order)))
                self.assertEqual(rb.size(), 1)

                raw = rb.read()
                self.assertIsNotNone(raw)
                unpacked = unpack_order(raw)
                self.assertEqual(unpacked.order_id, 300 + i)
                self.assertEqual(rb.size(), 0)

            # Monotonic indices should have advanced to total_cycles
            self.assertEqual(rb.write_idx, total_cycles)
            self.assertEqual(rb.read_idx, total_cycles)
        finally:
            rb.close()

    def test_full_buffer_handling(self):
        """4. Full buffer handling: rejects writes when full without overwriting unread data."""
        capacity = 4
        rb = RingBuffer(capacity=capacity, slot_size=ORDER_SIZE)
        try:
            for i in range(capacity):
                order = Order(order_id=400 + i, price=100.0, quantity=1, side=Side.BUY)
                self.assertTrue(rb.write(pack_order(order)))

            self.assertTrue(rb.is_full())
            self.assertEqual(rb.available_write(), 0)

            # Extra write must be rejected
            overflow_order = Order(order_id=999, price=100.0, quantity=1, side=Side.BUY)
            self.assertFalse(rb.write(pack_order(overflow_order)))
            self.assertEqual(rb.size(), capacity)

            # Verify unread slots were not corrupted or overwritten
            first = unpack_order(rb.read())
            self.assertEqual(first.order_id, 400)
            self.assertFalse(rb.is_full())

            # Now a new write should succeed
            self.assertTrue(rb.write(pack_order(overflow_order)))
        finally:
            rb.close()

    def test_empty_buffer_handling(self):
        """5. Empty buffer handling: returns None when empty without altering state."""
        rb = RingBuffer(capacity=8, slot_size=ORDER_SIZE)
        try:
            self.assertTrue(rb.is_empty())
            self.assertIsNone(rb.read())
            self.assertEqual(rb.read_idx, 0)
            self.assertEqual(rb.write_idx, 0)
        finally:
            rb.close()

    def test_concurrent_threads_no_loss_fifo(self):
        """6, 8, 9, 10, 11: Producer and consumer in concurrent threads with strict FIFO and zero loss."""
        capacity = 64
        total_orders = 1000
        rb = RingBuffer(capacity=capacity, slot_size=ORDER_SIZE)

        received_orders: List[Order] = []
        errors = []

        def producer():
            try:
                for i in range(total_orders):
                    order = Order(
                        order_id=5000 + i,
                        price=100.0 + (i % 20),
                        quantity=1 + (i % 10),
                        side=Side.BUY if i % 2 == 0 else Side.SELL,
                        timestamp_ns=2_000_000_000 + i,
                    )
                    payload = pack_order(order)
                    while not rb.write(payload):
                        time.sleep(0.00005)  # Backpressure wait
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                while len(received_orders) < total_orders:
                    raw = rb.read()
                    if raw is not None:
                        received_orders.append(unpack_order(raw))
                    else:
                        time.sleep(0.00005)
            except Exception as e:
                errors.append(e)

        t_prod = threading.Thread(target=producer)
        t_cons = threading.Thread(target=consumer)

        t_prod.start()
        t_cons.start()

        t_prod.join(timeout=10.0)
        t_cons.join(timeout=10.0)

        self.assertFalse(t_prod.is_alive(), "Producer thread timed out")
        self.assertFalse(t_cons.is_alive(), "Consumer thread timed out")
        self.assertEqual(len(errors), 0, f"Thread errors encountered: {errors}")

        # 8. No missing orders
        self.assertEqual(len(received_orders), total_orders)

        received_ids = [o.order_id for o in received_orders]
        # 9. No duplicate orders
        self.assertEqual(len(set(received_ids)), total_orders, "Duplicate order IDs detected!")

        # 10. No corrupted order records & 11. Strict FIFO ordering
        for i, order in enumerate(received_orders):
            expected_id = 5000 + i
            self.assertEqual(order.order_id, expected_id, f"FIFO mismatch at index {i}")
            self.assertAlmostEqual(order.price, 100.0 + (i % 20), places=2)
            self.assertEqual(order.quantity, 1 + (i % 10))
            self.assertEqual(order.side, Side.BUY if i % 2 == 0 else Side.SELL)
            self.assertEqual(order.timestamp_ns, 2_000_000_000 + i)

        rb.close()

    def test_separate_process_communication(self):
        """7. Separate-process communication using file-backed mmap with FIFO integrity."""
        fd, filepath = tempfile.mkstemp(prefix="chronos_ipc_test_", suffix=".mmap")
        os.close(fd)

        order_count = 500
        # Initialize file-backed ring buffer
        initializer = RingBuffer(capacity=128, filepath=filepath, create=True)
        initializer.close()

        err_q = Queue()
        res_q = Queue()

        p_prod = Process(target=_proc_producer, args=(filepath, order_count, err_q))
        p_cons = Process(target=_proc_consumer, args=(filepath, order_count, res_q, err_q))

        try:
            p_cons.start()
            p_prod.start()

            p_prod.join(timeout=15.0)
            p_cons.join(timeout=15.0)

            self.assertFalse(p_prod.is_alive(), "Producer process timed out")
            self.assertFalse(p_cons.is_alive(), "Consumer process timed out")

            errors = []
            while not err_q.empty():
                errors.append(err_q.get())
            self.assertEqual(len(errors), 0, f"Process errors: {errors}")

            self.assertFalse(res_q.empty(), "Consumer did not return received orders")
            received_ids = res_q.get()

            # Verify no missing, no duplicate, and strict FIFO
            expected_ids = [10_000 + i for i in range(order_count)]
            self.assertEqual(len(received_ids), order_count)
            self.assertEqual(received_ids, expected_ids)
        finally:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
