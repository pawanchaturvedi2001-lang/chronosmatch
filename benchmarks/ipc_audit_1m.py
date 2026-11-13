"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
IPC Ring Buffer 1-Million-Order Stress Audit (Phase 4)

Standalone executable benchmark and validation harness.
Verifies memory-mapped IPC ring buffer performance and reliability between
two independent operating system processes on Windows (using multiprocessing spawn).

Audits:
- Zero dropped / missing orders.
- Zero duplicate orders.
- Zero corrupted order records.
- Strict FIFO order preservation.
- Producer / consumer backpressure and synchronization.
- High-resolution throughput measurement.
"""

import argparse
import os
import platform
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field
from multiprocessing import Event, Process, Queue, freeze_support
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.ring_buffer import RingBuffer
from ipc.structures import (
    ORDER_FORMAT,
    ORDER_SIZE,
    ORDER_STRUCT,
    Order,
    Side,
    pack_order,
    unpack_order,
)


@dataclass
class AuditResult:
    """Telemetry and validation outcome from an IPC stress audit run."""
    stage_name: str
    target_orders: int
    received_orders: int
    missing_count: int
    duplicate_count: int
    unexpected_count: int
    fifo_violations: int
    corrupted_count: int
    producer_exit_code: int
    consumer_exit_code: int
    wall_duration_s: float
    wall_throughput_ops: float
    producer_duration_s: float
    producer_throughput_ops: float
    consumer_duration_s: float
    consumer_throughput_ops: float
    buffer_capacity: int
    slot_size: int
    python_version: str
    os_info: str
    sync_strategy: str
    passed: bool
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Worker: Producer Process
# ---------------------------------------------------------------------------
def _producer_process_entry(
    filepath: str,
    target_orders: int,
    capacity: int,
    start_order_id: int,
    err_queue: Queue,
    producer_done_event: Event,
    stop_event: Event,
):
    """
    Producer process entrypoint.

    Streams sequential, deterministically generated BUY/SELL orders into the
    memory-mapped ring buffer. Respects full-buffer backpressure using an
    adaptive backoff strategy without overwriting unread slots.
    """
    rb: Optional[RingBuffer] = None
    try:
        # Open existing memory-mapped buffer in consumer/producer child process
        rb = RingBuffer(capacity=capacity, filepath=filepath, create=False)
        orders_written = 0
        backpressure_retries = 0

        # Pre-bind fast pack method
        pack = ORDER_STRUCT.pack
        write_slot = rb.write

        start_time_ns = time.perf_counter_ns()

        for i in range(target_orders):
            order_id = start_order_id + i
            # Deterministic, realistic order parameters:
            # Alternating BUY (1) and SELL (2)
            side = 1 if (i & 1 == 0) else 2
            # Bounded price oscillating between 95.00 and 105.00 in 0.05 increments
            price = 95.0 + ((i % 200) * 0.05)
            # Quantity cycling between 5 and 100 shares
            quantity = 5 + (i % 96)
            timestamp_ns = time.time_ns()

            # Pack 29-byte order: <QdIBQ
            payload = pack(order_id, price, quantity, side, timestamp_ns)

            # Write into ring buffer with adaptive backpressure
            spins = 0
            while not write_slot(payload):
                backpressure_retries += 1
                if stop_event.is_set():
                    # Stop requested by coordinator or peer
                    break

                spins += 1
                if spins < 32:
                    # Tight spin for immediate availability
                    pass
                elif spins < 256:
                    # Yield time slice to OS scheduler (cooperative scheduling)
                    time.sleep(0)
                else:
                    # Micro-sleep to prevent 100% CPU lock when consumer is busy
                    time.sleep(0.0001)

            if stop_event.is_set():
                break

            orders_written += 1

        end_time_ns = time.perf_counter_ns()
        producer_duration_s = max(1e-9, (end_time_ns - start_time_ns) / 1e9)
        producer_throughput = orders_written / producer_duration_s

        # Signal completion to consumer
        producer_done_event.set()

        err_queue.put({
            "status": "SUCCESS",
            "orders_written": orders_written,
            "backpressure_retries": backpressure_retries,
            "duration_s": producer_duration_s,
            "throughput_ops": producer_throughput,
        })
    except Exception as exc:
        producer_done_event.set()
        err_queue.put({
            "status": "ERROR",
            "error": f"Producer fatal error: {exc}",
            "orders_written": orders_written if "orders_written" in locals() else 0,
        })
        sys.exit(1)
    finally:
        if rb is not None:
            rb.close()


# ---------------------------------------------------------------------------
# Worker: Consumer Process
# ---------------------------------------------------------------------------
def _consumer_process_entry(
    filepath: str,
    target_orders: int,
    capacity: int,
    start_order_id: int,
    result_queue: Queue,
    producer_done_event: Event,
    stop_event: Event,
):
    """
    Consumer process entrypoint.

    Reads 29-byte binary orders from the ring buffer, unpacks them via struct,
    and conducts immediate per-order validation for:
    - Expected sequential order ID (FIFO & completeness).
    - Valid bounds for price, quantity, side, timestamp.
    - Zero duplicates, gaps, or corruptions.
    """
    rb: Optional[RingBuffer] = None
    try:
        rb = RingBuffer(capacity=capacity, filepath=filepath, create=False)

        received_count = 0
        missing_count = 0
        duplicate_count = 0
        unexpected_count = 0
        fifo_violations = 0
        corrupted_count = 0
        expected_id = start_order_id

        # Track first and last ID for validation audit
        first_id_received = None
        last_id_received = None

        error_samples: List[str] = []

        # Pre-bind fast unpack and read methods
        unpack = ORDER_STRUCT.unpack
        read_slot = rb.read

        start_time_ns = time.perf_counter_ns()

        while received_count < target_orders:
            raw = read_slot()
            if raw is not None:
                # Validate raw payload size
                if len(raw) < ORDER_SIZE:
                    corrupted_count += 1
                    if len(error_samples) < 5:
                        error_samples.append(
                            f"Truncated slot: expected {ORDER_SIZE} bytes, got {len(raw)}"
                        )
                    continue

                try:
                    order_id, price, quantity, side, timestamp_ns = unpack(raw[:ORDER_SIZE])
                except struct.error as s_err:
                    corrupted_count += 1
                    if len(error_samples) < 5:
                        error_samples.append(f"Struct unpack error: {s_err}")
                    continue

                # 1. Sequence and FIFO validation
                if first_id_received is None:
                    first_id_received = order_id

                last_id_received = order_id

                if order_id == expected_id:
                    expected_id += 1
                elif order_id < expected_id:
                    # Duplicate or out-of-order backward jump
                    duplicate_count += 1
                    fifo_violations += 1
                    if len(error_samples) < 5:
                        error_samples.append(
                            f"Duplicate or backwards ID: got {order_id}, expected {expected_id}"
                        )
                else:
                    # Gap detected in sequential order IDs
                    gap = order_id - expected_id
                    missing_count += gap
                    fifo_violations += 1
                    if len(error_samples) < 5:
                        error_samples.append(
                            f"Missing ID gap: got {order_id}, expected {expected_id} (gap={gap})"
                        )
                    expected_id = order_id + 1

                # 2. Field integrity validation
                if price <= 0.0 or price > 1_000_000.0:
                    corrupted_count += 1
                    if len(error_samples) < 5:
                        error_samples.append(f"Corrupted price: {price} for order #{order_id}")

                if quantity <= 0 or quantity > 100_000_000:
                    corrupted_count += 1
                    if len(error_samples) < 5:
                        error_samples.append(f"Corrupted quantity: {quantity} for order #{order_id}")

                if side not in (1, 2):
                    corrupted_count += 1
                    if len(error_samples) < 5:
                        error_samples.append(f"Corrupted side: {side} for order #{order_id}")

                if timestamp_ns <= 0:
                    corrupted_count += 1
                    if len(error_samples) < 5:
                        error_samples.append(f"Invalid timestamp_ns: {timestamp_ns} for order #{order_id}")

                received_count += 1
            else:
                # Buffer empty
                if stop_event.is_set():
                    break

                # If producer finished and buffer is drained, but fewer orders received:
                if producer_done_event.is_set() and rb.is_empty():
                    # Double-check empty
                    if rb.is_empty() and received_count < target_orders:
                        if len(error_samples) < 5:
                            error_samples.append(
                                f"Producer exited prematurely: received {received_count}/{target_orders} orders"
                            )
                        break

                # Adaptive spin/sleep
                time.sleep(0)

        end_time_ns = time.perf_counter_ns()
        consumer_duration_s = max(1e-9, (end_time_ns - start_time_ns) / 1e9)
        consumer_throughput = received_count / consumer_duration_s

        result_queue.put({
            "status": "SUCCESS",
            "received_count": received_count,
            "missing_count": missing_count,
            "duplicate_count": duplicate_count,
            "unexpected_count": unexpected_count,
            "fifo_violations": fifo_violations,
            "corrupted_count": corrupted_count,
            "first_id": first_id_received,
            "last_id": last_id_received,
            "duration_s": consumer_duration_s,
            "throughput_ops": consumer_throughput,
            "error_samples": error_samples,
        })
    except Exception as exc:
        result_queue.put({
            "status": "ERROR",
            "error": f"Consumer fatal error: {exc}",
            "received_count": received_count if "received_count" in locals() else 0,
        })
        sys.exit(1)
    finally:
        if rb is not None:
            rb.close()


# ---------------------------------------------------------------------------
# Coordinator: Run Audit Stage
# ---------------------------------------------------------------------------
def run_ipc_audit(
    order_count: int = 1_000_000,
    capacity: int = 65_536,
    stage_name: Optional[str] = None,
    timeout: Optional[float] = None,
    start_order_id: int = 1_000_001,
    mmap_filepath: Optional[str] = None,
) -> AuditResult:
    """
    Executes an end-to-end IPC stress audit across two independent processes.

    Args:
        order_count: Total orders to generate, transmit, and verify.
        capacity: Ring buffer capacity in slots.
        stage_name: Optional label for the audit stage.
        timeout: Maximum seconds before aborting (default dynamically scaled).
        start_order_id: Starting integer for unique sequential IDs.
        mmap_filepath: Optional custom file path for backing mmap.

    Returns:
        AuditResult containing complete performance telemetry and validation flags.
    """
    if stage_name is None:
        stage_name = f"Audit-{order_count:,}"

    # Default timeout: scaled dynamically (min 15s, +1s per 30,000 orders)
    if timeout is None:
        timeout = max(15.0, 15.0 + (order_count / 30_000.0))

    created_temp_file = False
    if mmap_filepath is None:
        fd, mmap_filepath = tempfile.mkstemp(prefix="chronos_ipc_audit_", suffix=".mmap")
        os.close(fd)
        created_temp_file = True

    # 1. Initialize shared memory-mapped ring buffer
    init_rb = RingBuffer(capacity=capacity, filepath=mmap_filepath, create=True)
    init_rb.close()

    # 2. Inter-process synchronization and communication primitives
    prod_queue: Queue = Queue()
    cons_queue: Queue = Queue()
    producer_done_event = Event()
    stop_event = Event()

    p_consumer = Process(
        target=_consumer_process_entry,
        args=(
            mmap_filepath,
            order_count,
            capacity,
            start_order_id,
            cons_queue,
            producer_done_event,
            stop_event,
        ),
        name=f"ChronosConsumer-{order_count}",
    )

    p_producer = Process(
        target=_producer_process_entry,
        args=(
            mmap_filepath,
            order_count,
            capacity,
            start_order_id,
            prod_queue,
            producer_done_event,
            stop_event,
        ),
        name=f"ChronosProducer-{order_count}",
    )

    wall_start_ns = time.perf_counter_ns()

    try:
        # Start consumer first so it is ready to consume incoming slots
        p_consumer.start()
        # Start producer to generate and push orders
        p_producer.start()

        # Join producer with timeout
        p_producer.join(timeout=timeout)
        if p_producer.is_alive():
            stop_event.set()
            p_producer.terminate()
            p_producer.join(timeout=2.0)

        # Join consumer with remaining/reasonable timeout
        p_consumer.join(timeout=max(5.0, timeout / 2.0))
        if p_consumer.is_alive():
            stop_event.set()
            p_consumer.terminate()
            p_consumer.join(timeout=2.0)

    finally:
        stop_event.set()

    wall_end_ns = time.perf_counter_ns()
    wall_duration_s = max(1e-9, (wall_end_ns - wall_start_ns) / 1e9)

    prod_exit = p_producer.exitcode if p_producer.exitcode is not None else -999
    cons_exit = p_consumer.exitcode if p_consumer.exitcode is not None else -999

    # Retrieve telemetry from queues
    prod_data: Dict[str, Any] = {}
    cons_data: Dict[str, Any] = {}
    errors: List[str] = []

    try:
        if not prod_queue.empty():
            prod_data = prod_queue.get_nowait()
    except Exception:
        pass

    try:
        if not cons_queue.empty():
            cons_data = cons_queue.get_nowait()
    except Exception:
        pass

    if prod_data.get("status") == "ERROR":
        errors.append(prod_data.get("error", "Unknown producer error"))
    if cons_data.get("status") == "ERROR":
        errors.append(cons_data.get("error", "Unknown consumer error"))

    received_count = cons_data.get("received_count", 0)
    missing_count = cons_data.get("missing_count", 0)
    duplicate_count = cons_data.get("duplicate_count", 0)
    unexpected_count = cons_data.get("unexpected_count", 0)
    fifo_violations = cons_data.get("fifo_violations", 0)
    corrupted_count = cons_data.get("corrupted_count", 0)

    # Any samples captured by consumer
    if "error_samples" in cons_data and cons_data["error_samples"]:
        errors.extend(cons_data["error_samples"])

    # If count doesn't match and not recorded in missing_count
    if received_count != order_count and missing_count == 0:
        missing_count = order_count - received_count
        errors.append(f"Received count mismatch: expected {order_count:,}, got {received_count:,}")

    if prod_exit != 0:
        errors.append(f"Producer process non-zero exit code: {prod_exit}")
    if cons_exit != 0:
        errors.append(f"Consumer process non-zero exit code: {cons_exit}")

    producer_duration_s = prod_data.get("duration_s", wall_duration_s)
    producer_throughput = prod_data.get("throughput_ops", 0.0)

    consumer_duration_s = cons_data.get("duration_s", wall_duration_s)
    consumer_throughput = cons_data.get("throughput_ops", 0.0)

    wall_throughput = received_count / wall_duration_s

    # Strict audit validation rules:
    passed = (
        received_count == order_count
        and missing_count == 0
        and duplicate_count == 0
        and unexpected_count == 0
        and fifo_violations == 0
        and corrupted_count == 0
        and prod_exit == 0
        and cons_exit == 0
        and len(errors) == 0
    )

    # Cleanup temporary backing file
    if created_temp_file and os.path.exists(mmap_filepath):
        try:
            os.remove(mmap_filepath)
        except OSError:
            pass

    return AuditResult(
        stage_name=stage_name,
        target_orders=order_count,
        received_orders=received_count,
        missing_count=missing_count,
        duplicate_count=duplicate_count,
        unexpected_count=unexpected_count,
        fifo_violations=fifo_violations,
        corrupted_count=corrupted_count,
        producer_exit_code=prod_exit,
        consumer_exit_code=cons_exit,
        wall_duration_s=wall_duration_s,
        wall_throughput_ops=wall_throughput,
        producer_duration_s=producer_duration_s,
        producer_throughput_ops=producer_throughput,
        consumer_duration_s=consumer_duration_s,
        consumer_throughput_ops=consumer_throughput,
        buffer_capacity=capacity,
        slot_size=ORDER_SIZE,
        python_version=platform.python_version(),
        os_info=f"{platform.system()} {platform.release()} ({platform.machine()})",
        sync_strategy="SPSC lock-free memory-mapped ring buffer with independent monotonic sequence indices",
        passed=passed,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Formatting & Presentation
# ---------------------------------------------------------------------------
def print_audit_result(res: AuditResult):
    """Prints a structured, high-visibility audit summary table."""
    status_label = "[PASS]" if res.passed else "[FAIL]"
    border = "=" * 70

    print(f"\n{border}")
    print(f"CHRONOSMATCH IPC STRESS AUDIT — {res.stage_name.upper()} {status_label}")
    print(border)
    print(f"  Target Orders:        {res.target_orders:,}")
    print(f"  Received Orders:      {res.received_orders:,}")
    print(f"  Buffer Capacity:      {res.buffer_capacity:,} slots ({res.buffer_capacity * res.slot_size / 1024:.1f} KB)")
    print(f"  Order Record Size:    {res.slot_size} bytes (struct layout: '{ORDER_FORMAT}')")
    print(f"  Circular Wraparounds: {res.target_orders / res.buffer_capacity:.2f} cycles")
    print("-" * 70)
    print("INTEGRITY CHECKS:")
    print(f"  Missing IDs:          {res.missing_count} " + ("[OK]" if res.missing_count == 0 else "[FAIL]"))
    print(f"  Duplicate IDs:        {res.duplicate_count} " + ("[OK]" if res.duplicate_count == 0 else "[FAIL]"))
    print(f"  Unexpected IDs:       {res.unexpected_count} " + ("[OK]" if res.unexpected_count == 0 else "[FAIL]"))
    print(f"  FIFO Violations:      {res.fifo_violations} " + ("[OK]" if res.fifo_violations == 0 else "[FAIL]"))
    print(f"  Corrupted Records:    {res.corrupted_count} " + ("[OK]" if res.corrupted_count == 0 else "[FAIL]"))
    print(f"  Producer Exit Code:   {res.producer_exit_code} " + ("[OK]" if res.producer_exit_code == 0 else "[FAIL]"))
    print(f"  Consumer Exit Code:   {res.consumer_exit_code} " + ("[OK]" if res.consumer_exit_code == 0 else "[FAIL]"))
    print("-" * 70)
    print("PERFORMANCE METRICS:")
    print(f"  Wall Duration:        {res.wall_duration_s:.4f} s (including spawn/join)")
    print(f"  Wall Throughput:      {res.wall_throughput_ops:,.2f} orders/sec")
    print(f"  Producer Duration:    {res.producer_duration_s:.4f} s ({res.producer_throughput_ops:,.2f} orders/sec)")
    print(f"  Consumer Duration:    {res.consumer_duration_s:.4f} s ({res.consumer_throughput_ops:,.2f} orders/sec)")
    print("-" * 70)
    print("ENVIRONMENT & ARCHITECTURE:")
    print(f"  Python Runtime:       {res.python_version}")
    print(f"  Operating System:     {res.os_info}")
    print(f"  IPC Mechanism:        File-backed memory-mapped ring buffer (Windows mmap)")
    print(f"  Synchronization:      {res.sync_strategy}")

    if res.errors:
        print("-" * 70)
        print("DETECTED ANOMALIES:")
        for err in res.errors[:10]:
            print(f"  [!] {err}")

    print(border)
    if res.passed:
        print(f"RESULT: STAGE {res.stage_name} VERIFIED SUCCESSFULLY [PASS]")
    else:
        print(f"RESULT: STAGE {res.stage_name} FAILED AUDIT REQUIREMENTS [FAIL]")
    print(border + "\n")


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
def main():
    freeze_support()
    parser = argparse.ArgumentParser(
        description="ChronosMatch 1-Million-Order IPC Stress Audit and Throughput Benchmark."
    )
    parser.add_argument(
        "--orders",
        type=int,
        default=1_000_000,
        help="Number of orders to transfer and verify in a single run (default: 1,000,000).",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=65_536,
        help="Ring buffer capacity in slots (default: 65,536).",
    )
    parser.add_argument(
        "--all-stages",
        action="store_true",
        help="Execute stepped audit sequentially: Stage 1 (10k), Stage 2 (100k), Stage 3 (1,000,000).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Custom timeout in seconds for process execution.",
    )

    args = parser.parse_args()

    if args.all_stages:
        print("\n" + "=" * 70)
        print("CHRONOSMATCH STEPPED 3-STAGE IPC STRESS AUDIT")
        print("Executing sequential stages: 10,000 -> 100,000 -> 1,000,000 orders")
        print("=" * 70)

        stages = [
            ("Stage 1 (10k)", 10_000),
            ("Stage 2 (100k)", 100_000),
            ("Stage 3 (1M)", 1_000_000),
        ]

        all_passed = True
        stage_results: List[AuditResult] = []

        for stage_name, count in stages:
            print(f"\n--> Starting {stage_name}: {count:,} orders (Buffer Capacity: {args.capacity:,})...")
            res = run_ipc_audit(
                order_count=count,
                capacity=args.capacity,
                stage_name=stage_name,
                timeout=args.timeout,
            )
            print_audit_result(res)
            stage_results.append(res)

            if not res.passed:
                print(f"[!] Stage {stage_name} failed. Halting sequential audit.")
                all_passed = False
                sys.exit(1)

        print("\n" + "=" * 70)
        print("ALL 3 IPC AUDIT STAGES PASSED SUCCESSFULLY!")
        for res in stage_results:
            print(
                f"  * {res.stage_name:<16}: {res.target_orders:>10,} orders in {res.wall_duration_s:>6.3f}s | "
                f"Throughput: {res.wall_throughput_ops:>10,.2f} ops/sec [PASS]"
            )
        print("=" * 70 + "\n")
        sys.exit(0)

    else:
        stage_label = f"Single-Stage ({args.orders:,} orders)"
        res = run_ipc_audit(
            order_count=args.orders,
            capacity=args.capacity,
            stage_name=stage_label,
            timeout=args.timeout,
        )
        print_audit_result(res)
        sys.exit(0 if res.passed else 1)


if __name__ == "__main__":
    main()
