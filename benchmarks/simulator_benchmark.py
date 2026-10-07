"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
Simulator Throughput Benchmark (Member 3)

Measures real-world order generation and IPC ring buffer ingestion throughput.
Provides breakdown of total orders, elapsed time, orders/sec, backpressure retries,
and dropped orders.

Output adheres to the project benchmark specification:
    Orders generated: 100000
    Orders written:   100000
    Elapsed:           X.XX sec
    Throughput:        XXXXX orders/sec
    Dropped:           0
"""

import asyncio
import time
import argparse
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import ORDER_SIZE, unpack_order
from ipc.ring_buffer import RingBuffer
from simulator.market_simulator import MarketSimulator
from simulator.order_generator import OrderGeneratorConfig


async def mock_consumer(ring_buffer: RingBuffer, stop_event: asyncio.Event, consumed_counter: list):
    """
    Simulates the matching engine consumer draining orders from the ring buffer.
    Ensures the ring buffer does not deadlock when order count exceeds buffer capacity.
    """
    rb_read = ring_buffer.read
    count = 0
    while not stop_event.is_set():
        batch_read = 0
        while batch_read < 1000:
            data = rb_read()
            if data is not None:
                count += 1
                batch_read += 1
            else:
                break
        if batch_read == 0:
            await asyncio.sleep(0)
    # Drain any remaining orders after stop signal
    while True:
        data = rb_read()
        if data is None:
            break
        count += 1
    consumed_counter.append(count)


async def run_benchmark(
    total_orders: int = 100_000,
    target_rate: Optional[int] = None,
    buffer_capacity: int = 131_072,
    batch_size: int = 500,
    backpressure: str = "wait",
    with_consumer: bool = False,
    seed: Optional[int] = 42,
) -> dict:
    """
    Executes the throughput benchmark.

    Returns:
        dict with benchmark metrics.
    """
    ring_buffer = RingBuffer(capacity=buffer_capacity, slot_size=ORDER_SIZE)

    config = OrderGeneratorConfig(
        total_orders=total_orders,
        target_orders_per_sec=target_rate,
        seed=seed,
    )

    simulator = MarketSimulator(
        ring_buffer=ring_buffer,
        config=config,
        batch_size=batch_size,
        backpressure_mode=backpressure,
    )

    stop_event = asyncio.Event()
    consumed_counter = []
    consumer_task = None

    if with_consumer:
        consumer_task = asyncio.create_task(
            mock_consumer(ring_buffer, stop_event, consumed_counter)
        )

    # Measure elapsed time strictly
    start_time = time.perf_counter()
    stats = await simulator.run()
    elapsed = max(1e-9, time.perf_counter() - start_time)

    if consumer_task:
        stop_event.set()
        await consumer_task

    ring_buffer.close()

    actual_throughput = stats.orders_written / elapsed

    results = {
        "orders_generated": stats.orders_generated,
        "orders_written": stats.orders_written,
        "elapsed": elapsed,
        "throughput": actual_throughput,
        "dropped": stats.orders_dropped,
        "retries": stats.orders_retried,
        "failed_writes": stats.failed_writes,
        "history": stats.throughput_history,
    }

    return results


def print_results(res: dict):
    """Prints benchmark metrics in the required format."""
    print()
    print("=" * 45)
    print("      CHRONOSMATCH BENCHMARK RESULTS         ")
    print("=" * 45)
    print(f"Orders generated: {res['orders_generated']}")
    print(f"Orders written:   {res['orders_written']}")
    print(f"Elapsed:          {res['elapsed']:.2f} sec")
    print(f"Throughput:       {res['throughput']:,.0f} orders/sec")
    print(f"Dropped:          {res['dropped']}")
    if res["retries"] > 0:
        print(f"Retries:          {res['retries']}")
    if res["failed_writes"] > 0:
        print(f"Failed writes:    {res['failed_writes']}")
    print("=" * 45)

    if res.get("history"):
        print("\nThroughput Over Time:")
        print(f"{'Elapsed (s)':<12} | {'Orders Written':<16} | {'Interval Rate (orders/s)':<24}")
        print("-" * 58)
        for entry in res["history"]:
            print(
                f"{entry['elapsed']:<12.3f} | {entry['orders_written']:<16,} | {entry['interval_rate']:<24,.1f}"
            )
        print("-" * 58)


def main():
    parser = argparse.ArgumentParser(
        description="ChronosMatch Market Simulator Throughput Benchmark"
    )
    parser.add_argument(
        "--orders",
        type=int,
        default=100_000,
        help="Total orders to blast (default: 100,000)",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=0,
        help="Target rate limit in orders/sec (default: 0 = unthrottled maximum)",
    )
    parser.add_argument(
        "--buffer-capacity",
        type=int,
        default=131_072,
        help="Ring buffer slot capacity (default: 131,072)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size per event loop yield (default: 500)",
    )
    parser.add_argument(
        "--backpressure",
        choices=["wait", "drop"],
        default="wait",
        help="Backpressure mode when buffer fills up (default: wait)",
    )
    parser.add_argument(
        "--with-consumer",
        action="store_true",
        help="Run concurrent mock consumer draining orders",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible benchmark (default: 42)",
    )

    args = parser.parse_args()
    target_rate = args.rate if args.rate > 0 else None

    print(f"Running benchmark with {args.orders:,} orders...")
    print(f"Buffer capacity: {args.buffer_capacity:,} slots")
    print(f"Backpressure mode: {args.backpressure}")
    print(f"Concurrent consumer: {'Enabled' if args.with_consumer else 'Disabled'}")

    res = asyncio.run(
        run_benchmark(
            total_orders=args.orders,
            target_rate=target_rate,
            buffer_capacity=args.buffer_capacity,
            batch_size=args.batch_size,
            backpressure=args.backpressure,
            with_consumer=args.with_consumer,
            seed=args.seed,
        )
    )

    print_results(res)


if __name__ == "__main__":
    main()
