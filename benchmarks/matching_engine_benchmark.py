"""
ChronosMatch Matching Engine & Latency Benchmark (Week 2)
Measures:
1. Pure Engine-Only Matching Throughput and Latency Distribution (P50, P90, P95, P99, Max).
2. End-to-End Pipeline Performance (Simulator -> IPC RingBuffer -> Consumer -> LOB).
3. GIL and Native Acceleration Verification.
"""

import time
import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import Order, Side, ORDER_SIZE
from ipc.ring_buffer import RingBuffer
from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from core.engine import ChronosEngine
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig


def benchmark_engine_only(order_count: int = 100_000, seed: int = 42) -> Dict[str, Any]:
    """
    Measures raw matching engine performance without IPC or generator overhead.
    """
    print(f"\n[1/2] Generating {order_count:,} test orders for engine-only benchmark...")
    config = OrderGeneratorConfig(
        initial_order_id=1001,
        total_orders=order_count,
        min_price=95.00,
        max_price=105.00,
        buy_ratio=0.50,
        seed=seed,
    )
    generator = OrderGenerator(config)
    orders = generator.generate_batch(order_count)

    lob = LimitOrderBook(tick_size=0.01)
    process_order = lob.process_order

    latencies_ns = np.empty(order_count, dtype=np.int64)

    print(f"Running engine matching on {order_count:,} orders...")
    t_start = time.perf_counter()

    for i in range(order_count):
        order = orders[i]
        t0 = time.perf_counter_ns()
        process_order(order)
        t1 = time.perf_counter_ns()
        latencies_ns[i] = t1 - t0

    t_end = time.perf_counter()
    total_elapsed = max(1e-9, t_end - t_start)
    throughput = order_count / total_elapsed

    latencies_us = latencies_ns / 1000.0

    return {
        "order_count": order_count,
        "elapsed_sec": total_elapsed,
        "throughput": throughput,
        "trades_executed": lob.total_trades_executed,
        "volume_executed": lob.total_volume_executed,
        "lat_mean_us": float(np.mean(latencies_us)),
        "lat_p50_us": float(np.percentile(latencies_us, 50)),
        "lat_p90_us": float(np.percentile(latencies_us, 90)),
        "lat_p95_us": float(np.percentile(latencies_us, 95)),
        "lat_p99_us": float(np.percentile(latencies_us, 99)),
        "lat_max_us": float(np.max(latencies_us)),
    }


async def benchmark_pipeline(order_count: int = 100_000, buffer_capacity: int = 131_072, seed: int = 42) -> Dict[str, Any]:
    """
    Measures end-to-end pipeline throughput over shared-memory RingBuffer IPC.
    """
    print(f"\n[2/2] Running end-to-end pipeline benchmark with {order_count:,} orders...")
    ring_buf = RingBuffer(capacity=buffer_capacity, slot_size=ORDER_SIZE)
    lob = LimitOrderBook(tick_size=0.01)
    engine = ChronosEngine(ring_buffer=ring_buf, lob=lob, batch_size=500)

    results = await engine.start_pipeline(
        total_orders=order_count,
        target_rate=None,  # unthrottled
        with_dashboard=False,
        seed=seed,
    )
    ring_buf.close()
    return results


def print_report(engine_res: Dict[str, Any], pipe_res: Optional[Dict[str, Any]] = None):
    """Print structured benchmark results table."""
    mode_str = "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON FALLBACK"

    print("\n" + "=" * 65)
    print("      CHRONOSMATCH MATCHING ENGINE BENCHMARK REPORT")
    print("=" * 65)
    print(f"Engine Implementation:  {mode_str}")
    print(f"GIL Context:            {'Cnogil inner math + GIL Python objects' if IS_NATIVE_CYTHON else 'Standard CPython GIL'}")
    print("-" * 65)
    print("  PHASE 1: ENGINE-ONLY MATCHING (Zero IPC Overhead)")
    print("-" * 65)
    print(f"Orders Submitted:       {engine_res['order_count']:,}")
    print(f"Trades Executed:        {engine_res['trades_executed']:,}")
    print(f"Total Volume Matched:   {engine_res['volume_executed']:,}")
    print(f"Elapsed Time:           {engine_res['elapsed_sec']:.4f} sec")
    print(f"Engine Throughput:      {engine_res['throughput']:,.1f} orders/sec")
    print("\nLatency Distribution (per-order match latency):")
    print(f"  Average (Mean):       {engine_res['lat_mean_us']:>8.2f} us")
    print(f"  P50 (Median):         {engine_res['lat_p50_us']:>8.2f} us")
    print(f"  P90:                  {engine_res['lat_p90_us']:>8.2f} us")
    print(f"  P95:                  {engine_res['lat_p95_us']:>8.2f} us")
    print(f"  P99:                  {engine_res['lat_p99_us']:>8.2f} us")
    print(f"  Max Latency:          {engine_res['lat_max_us']:>8.2f} us")

    if pipe_res:
        print("\n" + "-" * 65)
        print("  PHASE 2: END-TO-END PIPELINE (Simulator -> RingBuffer -> LOB)")
        print("-" * 65)
        print(f"Orders Written (IPC):   {pipe_res['orders_written']:,}")
        print(f"Orders Consumed & Exec: {pipe_res['orders_consumed']:,}")
        print(f"Trades Executed:        {pipe_res['trades_generated']:,}")
        print(f"Producer Elapsed:       {pipe_res['producer_elapsed']:.4f} sec")
        print(f"Consumer Elapsed:       {pipe_res['consumer_elapsed']:.4f} sec")
        print(f"Producer Ingest Rate:   {pipe_res['producer_throughput']:,.1f} orders/sec")
        print(f"Consumer Match Rate:    {pipe_res['consumer_throughput']:,.1f} orders/sec")
        print(f"Dropped Orders:         {pipe_res['dropped']}")
        print(f"Backpressure Retries:   {pipe_res['retries']}")

    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="ChronosMatch Matching Engine & Latency Benchmark"
    )
    parser.add_argument(
        "--orders", type=int, default=100_000, help="Total orders to benchmark (default: 100,000)"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducible order stream (default: 42)"
    )
    parser.add_argument(
        "--skip-pipeline", action="store_true", help="Skip end-to-end pipeline benchmark"
    )
    args = parser.parse_args()

    engine_res = benchmark_engine_only(order_count=args.orders, seed=args.seed)

    pipe_res = None
    if not args.skip_pipeline:
        pipe_res = asyncio.run(benchmark_pipeline(order_count=args.orders, seed=args.seed))

    print_report(engine_res, pipe_res)


if __name__ == "__main__":
    main()
