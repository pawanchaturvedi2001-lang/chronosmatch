"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
IPC 1-Million-Order Stress Audit Test Suite (Phase 4)

Validates:
1. Small producer/consumer run across separate processes.
2. Strict FIFO ordering verification.
3. Duplicate order detection logic.
4. Missing order / sequence gap detection logic.
5. Corrupted record detection logic.
6. Premature producer termination / failure handling.
7. Premature consumer failure handling.
8. Process timeout handling and safe child process termination.
9. Verification of true separate-process communication.
"""

import os
import struct
import tempfile
import time
import unittest
from multiprocessing import Event, Process, Queue

from benchmarks.ipc_audit_1m import (
    AuditResult,
    _consumer_process_entry,
    _producer_process_entry,
    run_ipc_audit,
)
from ipc.ring_buffer import RingBuffer
from ipc.structures import (
    ORDER_SIZE,
    ORDER_STRUCT,
    Order,
    Side,
    pack_order,
    unpack_order,
)


class TestIPCAuditModule(unittest.TestCase):
    """Test suite for the IPC stress audit engine and reliability validators."""

    def test_small_producer_consumer_run(self):
        """1. Small producer/consumer run across separate processes."""
        order_count = 2_000
        capacity = 256  # Forces ~7.8 circular wraparounds

        res: AuditResult = run_ipc_audit(
            order_count=order_count,
            capacity=capacity,
            stage_name="Test-Small-2k",
            timeout=10.0,
        )

        self.assertTrue(res.passed, f"Audit failed with errors: {res.errors}")
        self.assertEqual(res.received_orders, order_count)
        self.assertEqual(res.missing_count, 0)
        self.assertEqual(res.duplicate_count, 0)
        self.assertEqual(res.unexpected_count, 0)
        self.assertEqual(res.fifo_violations, 0)
        self.assertEqual(res.corrupted_count, 0)
        self.assertEqual(res.producer_exit_code, 0)
        self.assertEqual(res.consumer_exit_code, 0)
        self.assertGreater(res.wall_throughput_ops, 1_000.0)

    def test_fifo_ordering_and_integrity(self):
        """2. Strict FIFO ordering and parameter integrity across circular buffer."""
        order_count = 1_000
        capacity = 64  # Forces 15.6 wraparounds

        res = run_ipc_audit(
            order_count=order_count,
            capacity=capacity,
            stage_name="Test-FIFO-1k",
            timeout=10.0,
            start_order_id=50_001,
        )

        self.assertTrue(res.passed)
        self.assertEqual(res.fifo_violations, 0)
        self.assertEqual(res.missing_count, 0)
        self.assertEqual(res.duplicate_count, 0)

    def test_duplicate_detection_logic(self):
        """3. Duplicate order detection logic catches duplicate IDs."""
        fd, path = tempfile.mkstemp(prefix="test_audit_dup_", suffix=".mmap")
        os.close(fd)
        try:
            capacity = 128
            rb = RingBuffer(capacity=capacity, filepath=path, create=True)

            # Write normal order 101, then duplicate 101, then 102
            pack = ORDER_STRUCT.pack
            rb.write(pack(101, 100.0, 10, 1, 1000))
            rb.write(pack(101, 100.0, 10, 1, 1001))  # Duplicate!
            rb.write(pack(102, 100.0, 10, 1, 1002))
            rb.close()

            res_q = Queue()
            prod_done = Event()
            prod_done.set()
            stop_ev = Event()

            p_cons = Process(
                target=_consumer_process_entry,
                args=(path, 3, capacity, 101, res_q, prod_done, stop_ev),
            )
            p_cons.start()
            p_cons.join(timeout=5.0)

            self.assertFalse(res_q.empty())
            data = res_q.get()
            self.assertEqual(data["status"], "SUCCESS")
            self.assertEqual(data["received_count"], 3)
            self.assertGreater(data["duplicate_count"], 0)
            self.assertGreater(data["fifo_violations"], 0)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_missing_order_detection_logic(self):
        """4. Missing order / sequence gap detection logic catches skipped IDs."""
        fd, path = tempfile.mkstemp(prefix="test_audit_gap_", suffix=".mmap")
        os.close(fd)
        try:
            capacity = 128
            rb = RingBuffer(capacity=capacity, filepath=path, create=True)

            # Write order 201, then skip 202 and 203 to write 204
            pack = ORDER_STRUCT.pack
            rb.write(pack(201, 100.0, 10, 1, 1000))
            rb.write(pack(204, 100.0, 10, 1, 1001))  # Gap of 2 orders!
            rb.close()

            res_q = Queue()
            prod_done = Event()
            prod_done.set()
            stop_ev = Event()

            p_cons = Process(
                target=_consumer_process_entry,
                args=(path, 2, capacity, 201, res_q, prod_done, stop_ev),
            )
            p_cons.start()
            p_cons.join(timeout=5.0)

            self.assertFalse(res_q.empty())
            data = res_q.get()
            self.assertEqual(data["status"], "SUCCESS")
            self.assertEqual(data["received_count"], 2)
            self.assertEqual(data["missing_count"], 2)
            self.assertGreater(data["fifo_violations"], 0)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_corruption_detection_logic(self):
        """5. Corrupted record detection catches invalid prices, quantities, and sides."""
        fd, path = tempfile.mkstemp(prefix="test_audit_corrupt_", suffix=".mmap")
        os.close(fd)
        try:
            capacity = 128
            rb = RingBuffer(capacity=capacity, filepath=path, create=True)

            pack = ORDER_STRUCT.pack
            # Valid order
            rb.write(pack(301, 100.0, 10, 1, 1000))
            # Invalid price (<= 0)
            rb.write(pack(302, -5.0, 10, 1, 1001))
            # Invalid quantity (0)
            rb.write(pack(303, 100.0, 0, 1, 1002))
            # Invalid side (99)
            rb.write(pack(304, 100.0, 10, 99, 1003))
            rb.close()

            res_q = Queue()
            prod_done = Event()
            prod_done.set()
            stop_ev = Event()

            p_cons = Process(
                target=_consumer_process_entry,
                args=(path, 4, capacity, 301, res_q, prod_done, stop_ev),
            )
            p_cons.start()
            p_cons.join(timeout=5.0)

            self.assertFalse(res_q.empty())
            data = res_q.get()
            self.assertEqual(data["status"], "SUCCESS")
            self.assertEqual(data["received_count"], 4)
            self.assertEqual(data["corrupted_count"], 3)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_producer_failure_handling(self):
        """6. Producer premature exit/failure is detected and does not freeze consumer."""
        fd, path = tempfile.mkstemp(prefix="test_audit_prodfail_", suffix=".mmap")
        os.close(fd)
        try:
            capacity = 128
            rb = RingBuffer(capacity=capacity, filepath=path, create=True)

            # Producer writes 50 orders then terminates, when 100 were expected
            pack = ORDER_STRUCT.pack
            for i in range(50):
                rb.write(pack(401 + i, 100.0, 10, 1, 1000 + i))
            rb.close()

            res_q = Queue()
            prod_done = Event()
            prod_done.set()  # Producer is finished
            stop_ev = Event()

            t0 = time.perf_counter()
            p_cons = Process(
                target=_consumer_process_entry,
                args=(path, 100, capacity, 401, res_q, prod_done, stop_ev),
            )
            p_cons.start()
            p_cons.join(timeout=5.0)
            elapsed = time.perf_counter() - t0

            # Consumer must terminate quickly without waiting out full timeout
            self.assertFalse(p_cons.is_alive())
            self.assertLess(elapsed, 4.0)

            self.assertFalse(res_q.empty())
            data = res_q.get()
            self.assertEqual(data["received_count"], 50)
            # Recorded premature termination sample
            self.assertTrue(
                any("prematurely" in s for s in data.get("error_samples", [])),
                f"Expected premature exit error, got {data.get('error_samples')}",
            )
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_consumer_failure_handling(self):
        """7. Producer stops cleanly when stop_event is signaled during full-buffer."""
        fd, path = tempfile.mkstemp(prefix="test_audit_consfail_", suffix=".mmap")
        os.close(fd)
        try:
            capacity = 16  # Very small buffer
            rb = RingBuffer(capacity=capacity, filepath=path, create=True)
            rb.close()

            err_q = Queue()
            prod_done = Event()
            stop_ev = Event()

            # Target 10,000 orders into capacity-16 buffer with NO consumer running
            p_prod = Process(
                target=_producer_process_entry,
                args=(path, 10_000, capacity, 1001, err_q, prod_done, stop_ev),
            )
            p_prod.start()

            # Let producer fill buffer and enter backpressure wait
            time.sleep(0.1)

            # Signal consumer failure/stop
            t0 = time.perf_counter()
            stop_ev.set()
            p_prod.join(timeout=3.0)
            elapsed = time.perf_counter() - t0

            self.assertFalse(p_prod.is_alive(), "Producer did not terminate on stop_event")
            self.assertLess(elapsed, 2.0)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_timeout_handling(self):
        """8. Audit timeout aborts child processes cleanly without hanging."""
        # Request 500k orders with an impossibly short timeout of 0.05s
        res = run_ipc_audit(
            order_count=500_000,
            capacity=16,
            stage_name="Test-Timeout",
            timeout=0.05,
        )

        self.assertFalse(res.passed)
        # Verify that process was terminated and didn't hang
        self.assertLess(res.wall_duration_s, 5.0)

    def test_separate_process_communication(self):
        """9. Verification that producer and consumer execute in separate processes."""
        order_count = 500
        capacity = 64

        res = run_ipc_audit(
            order_count=order_count,
            capacity=capacity,
            stage_name="Test-Separate-Proc",
            timeout=10.0,
        )

        self.assertTrue(res.passed)
        self.assertEqual(res.producer_exit_code, 0)
        self.assertEqual(res.consumer_exit_code, 0)


if __name__ == "__main__":
    unittest.main()
