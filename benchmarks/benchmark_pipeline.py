"""
ChronosMatch Formal End-to-End Pipeline Benchmarks (Phase 5)
Measures the complete trading workflow:
    Market Simulator
      -> Zero-Copy Binary Serialization (pack_order, 29B)
      -> Shared-Memory Memory-Mapped IPC Ring Buffer
      -> Consumer Worker
      -> Cython Limit Order Book Matching Engine
      -> Trade Execution & State Update

Accurately measures and cleanly separates:
1. Engine Latency: Pure LimitOrderBook.process_order execution time.
2. IPC Transit Latency: Nanoseconds spent in RingBuffer queue transit.
3. End-to-End Latency: From simulator order generation timestamp to post-match completion.

All latencies use time.perf_counter_ns().
Percentiles (P50, P90, P95, P99) and statistics (Mean, Min, Max) are reported in microseconds (us).
"""

import sys
import os
import time
import asyncio
import argparse
from pathlib import Path
from typing import Dict, Any, List
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import Order, Side, ORDER_SIZE
from ipc.ring_buffer import RingBuffer
from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from core.engine import ChronosEngine
from monitoring.latency import PipelineLatencyMonitor, LatencyTracker


async def run_pipeline_benchmark(
    order_count: int = 100_000,
    buffer_capacity: int = 131_072,
    batch_size: int = 500,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Execute end-to-end simulation, ingestion, matching, and telemetry.
    """
    ring_buf = RingBuffer(capacity=buffer_capacity, slot_size=ORDER_SIZE)
    lob = LimitOrderBook(tick_size=0.01)
    engine = ChronosEngine(ring_buffer=ring_buf, lob=lob, batch_size=batch_size)

    t_start = time.perf_counter()
    pipeline_res = await engine.start_pipeline(
        total_orders=order_count,
        target_rate=0,  # Unthrottled maximum throughput
        with_dashboard=False,
        seed=seed,
        auto_exit=True,
    )
    t_end = time.perf_counter()
    wall_duration = max(1e-9, t_end - t_start)
    ring_buf.close()

    eng_stats = engine.latency_monitor.engine_tracker.get_stats()
    e2e_stats = engine.latency_monitor.e2e_tracker.get_stats()
    ipc_stats = engine.latency_monitor.ipc_tracker.get_stats()

    throughput = order_count / wall_duration

    return {
        "order_count": order_count,
        "buffer_capacity": buffer_capacity,
        "wall_duration_sec": wall_duration,
        "throughput_ops": throughput,
        "orders_consumed": pipeline_res["orders_consumed"],
        "trades_generated": pipeline_res["trades_generated"],
        "sweeps_detected": getattr(lob, "total_sweeps_detected", 0),
        "engine_mode": "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON",
        # Engine Latencies (us)
        "engine_mean_us": eng_stats["engine_match_mean_us"],
        "engine_p50_us": eng_stats["engine_match_p50_us"],
        "engine_p90_us": eng_stats["engine_match_p90_us"],
        "engine_p95_us": eng_stats["engine_match_p95_us"],
        "engine_p99_us": eng_stats["engine_match_p99_us"],
        "engine_max_us": eng_stats["engine_match_max_us"],
        # End-to-End Latencies (us)
        "e2e_mean_us": e2e_stats["pipeline_e2e_mean_us"],
        "e2e_p50_us": e2e_stats["pipeline_e2e_p50_us"],
        "e2e_p90_us": e2e_stats["pipeline_e2e_p90_us"],
        "e2e_p95_us": e2e_stats["pipeline_e2e_p95_us"],
        "e2e_p99_us": e2e_stats["pipeline_e2e_p99_us"],
        "e2e_max_us": e2e_stats["pipeline_e2e_max_us"],
    }


def print_pipeline_report(results: List[Dict[str, Any]]):
    """Pretty-print complete end-to-end pipeline benchmark results."""
    print("\n" + "=" * 108)
    print(f"{'STAGE / WORKLOAD':<28} | {'ORDERS':>8} | {'THROUGHPUT':>12} | {'ENG MEAN':>9} | {'ENG P95':>8} | {'ENG P99':>8} | {'E2E MEAN':>9} | {'E2E P99':>8}")
    print(f"{'':<28} | {'':>8} | {'(orders/s)':>12} | {'(us)':>9} | {'(us)':>8} | {'(us)':>8} | {'(us)':>9} | {'(us)':>8}")
    print("-" * 108)
    for r in results:
        print(
            f"End-to-End Pipeline ({r['order_count']:,}) {'':<4} | {r['order_count']:>8,} | {r['throughput_ops']:>12,.1f} | "
            f"{r['engine_mean_us']:>9.2f} | {r['engine_p95_us']:>8.2f} | {r['engine_p99_us']:>8.2f} | "
            f"{r['e2e_mean_us']:>9.2f} | {r['e2e_p99_us']:>8.2f}"
        )
    print("=" * 108 + "\n")


def run_all_pipeline_benchmarks(sizes: List[int] = None) -> List[Dict[str, Any]]:
    if sizes is None:
        sizes = [10_000, 100_000]

    all_results = []
    print("\n" + "#" * 70)
    print("CHRONOSMATCH END-TO-END PIPELINE FORMAL BENCHMARK")
    print(f"Workflow: Simulator -> Struct Pack -> mmap RingBuffer -> Cython LOB")
    print(f"Engine Acceleration: {'CYTHON NATIVE' if IS_NATIVE_CYTHON else 'PURE PYTHON FALLBACK'}")
    print("#" * 70)

    for n in sizes:
        print(f"\n--> Executing End-to-End Pipeline on {n:,} orders...")
        res = asyncio.run(run_pipeline_benchmark(order_count=n))
        all_results.append(res)
        print(f"    Completed in {res['wall_duration_sec']:.3f} s | Throughput: {res['throughput_ops']:,.1f} orders/sec")
        print(f"    Trades Executed: {res['trades_generated']:,} | Sweeps Detected: {res['sweeps_detected']:,}")
        print(f"    Engine Match Latency: Mean: {res['engine_mean_us']:.2f} us | P95: {res['engine_p95_us']:.2f} us | P99: {res['engine_p99_us']:.2f} us")
        print(f"    End-to-End Latency:   Mean: {res['e2e_mean_us']:.2f} us | P95: {res['e2e_p95_us']:.2f} us | P99: {res['e2e_p99_us']:.2f} us")

    print_pipeline_report(all_results)
    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChronosMatch End-to-End Pipeline Benchmark")
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 100000],
                        help="Order counts for pipeline benchmark (default: 10000 100000)")
    args = parser.parse_args()
    run_all_pipeline_benchmarks(args.sizes)
