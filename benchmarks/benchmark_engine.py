"""
ChronosMatch Formal Matching Engine Benchmark Suite (Phase 5)
Measures:
1. Order Insertion Latency (resting orders)
2. BUY Order Matching Latency (aggressive incoming BUY matching resting asks)
3. SELL Order Matching Latency (aggressive incoming SELL matching resting bids)
4. Partial-Fill Execution Latency (incoming order partially matches resting quantity)
5. Multi-Level Sweep Latency (incoming order sweeps across 2+ price levels)
6. Continuous High-Throughput Realistic Workloads (10k, 100k, 1M orders)

All timing measurements use time.perf_counter_ns().
Percentiles (P50, P90, P95, P99) and statistics (Mean, Min, Max) are computed in microseconds (us).
"""

import sys
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Tuple
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import Order, Side, SIDE_BUY, SIDE_SELL
from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig
from monitoring.latency import LatencyTracker


def calculate_distribution(latencies_ns: np.ndarray) -> Dict[str, float]:
    """Convert nanosecond array to microsecond summary statistics."""
    if len(latencies_ns) == 0:
        return {
            "mean_us": 0.0,
            "min_us": 0.0,
            "p50_us": 0.0,
            "p90_us": 0.0,
            "p95_us": 0.0,
            "p99_us": 0.0,
            "max_us": 0.0,
        }
    lat_us = latencies_ns / 1000.0
    return {
        "mean_us": float(np.mean(lat_us)),
        "min_us": float(np.min(lat_us)),
        "p50_us": float(np.percentile(lat_us, 50)),
        "p90_us": float(np.percentile(lat_us, 90)),
        "p95_us": float(np.percentile(lat_us, 95)),
        "p99_us": float(np.percentile(lat_us, 99)),
        "max_us": float(np.max(lat_us)),
    }


def warmup_engine(lob: LimitOrderBook, warmup_orders: int = 5000):
    """Warm up instruction cache and Python/Cython method dispatch."""
    process = lob.process_order
    for i in range(1, warmup_orders + 1):
        side = Side.BUY if (i % 2 == 0) else Side.SELL
        price = 100.0 - (i % 50) * 0.01 if side == Side.BUY else 100.0 + (i % 50) * 0.01
        order = Order(order_id=i, price=price, quantity=10, side=side, timestamp_ns=time.perf_counter_ns())
        process(order)


def benchmark_order_insertion(count: int = 10000) -> Dict[str, Any]:
    """Measure latency and throughput of passive order insertion (non-crossing resting orders)."""
    lob = LimitOrderBook(tick_size=0.01)
    warmup_engine(lob, 2000)
    lob = LimitOrderBook(tick_size=0.01)

    # Generate non-crossing orders: BUY below 95.00, SELL above 105.00
    orders = []
    for i in range(count):
        if i % 2 == 0:
            price = 90.00 - (i % 1000) * 0.01
            side = Side.BUY
        else:
            price = 110.00 + (i % 1000) * 0.01
            side = Side.SELL
        orders.append(Order(order_id=100000 + i, price=price, quantity=10, side=side, timestamp_ns=0))

    process = lob.process_order
    latencies = np.empty(count, dtype=np.int64)

    t_start = time.perf_counter_ns()
    for i in range(count):
        t0 = time.perf_counter_ns()
        process(orders[i])
        t1 = time.perf_counter_ns()
        latencies[i] = t1 - t0
    t_end = time.perf_counter_ns()

    elapsed_sec = (t_end - t_start) / 1e9
    stats = calculate_distribution(latencies)
    stats.update({
        "name": "Order Insertion (Passive)",
        "count": count,
        "elapsed_sec": elapsed_sec,
        "throughput_ops": count / elapsed_sec if elapsed_sec > 0 else 0.0,
    })
    return stats


def benchmark_buy_matching(count: int = 10000) -> Dict[str, Any]:
    """Measure latency of aggressive BUY orders matching resting asks."""
    lob = LimitOrderBook(tick_size=0.01)
    process = lob.process_order

    # Pre-populate resting asks
    for i in range(count):
        process(Order(order_id=100000 + i, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=0))

    # Prepare aggressive incoming BUY orders
    buy_orders = [
        Order(order_id=200000 + i, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=0)
        for i in range(count)
    ]

    latencies = np.empty(count, dtype=np.int64)
    t_start = time.perf_counter_ns()
    for i in range(count):
        t0 = time.perf_counter_ns()
        process(buy_orders[i])
        t1 = time.perf_counter_ns()
        latencies[i] = t1 - t0
    t_end = time.perf_counter_ns()

    elapsed_sec = (t_end - t_start) / 1e9
    stats = calculate_distribution(latencies)
    stats.update({
        "name": "BUY Order Matching (Aggressive)",
        "count": count,
        "elapsed_sec": elapsed_sec,
        "throughput_ops": count / elapsed_sec if elapsed_sec > 0 else 0.0,
        "trades_executed": lob.total_trades_executed,
    })
    return stats


def benchmark_sell_matching(count: int = 10000) -> Dict[str, Any]:
    """Measure latency of aggressive SELL orders matching resting bids."""
    lob = LimitOrderBook(tick_size=0.01)
    process = lob.process_order

    # Pre-populate resting bids
    for i in range(count):
        process(Order(order_id=100000 + i, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=0))

    # Prepare aggressive incoming SELL orders
    sell_orders = [
        Order(order_id=200000 + i, price=100.00, quantity=10, side=Side.SELL, timestamp_ns=0)
        for i in range(count)
    ]

    latencies = np.empty(count, dtype=np.int64)
    t_start = time.perf_counter_ns()
    for i in range(count):
        t0 = time.perf_counter_ns()
        process(sell_orders[i])
        t1 = time.perf_counter_ns()
        latencies[i] = t1 - t0
    t_end = time.perf_counter_ns()

    elapsed_sec = (t_end - t_start) / 1e9
    stats = calculate_distribution(latencies)
    stats.update({
        "name": "SELL Order Matching (Aggressive)",
        "count": count,
        "elapsed_sec": elapsed_sec,
        "throughput_ops": count / elapsed_sec if elapsed_sec > 0 else 0.0,
        "trades_executed": lob.total_trades_executed,
    })
    return stats


def benchmark_partial_fill(count: int = 10000) -> Dict[str, Any]:
    """Measure partial-fill execution latency."""
    lob = LimitOrderBook(tick_size=0.01)
    process = lob.process_order

    # Pre-populate 1 large resting sell order of 100,000 units
    process(Order(order_id=1, price=100.00, quantity=count * 10, side=Side.SELL, timestamp_ns=0))

    # Match in small partial fills of 10 units each
    buy_orders = [
        Order(order_id=1000 + i, price=100.00, quantity=10, side=Side.BUY, timestamp_ns=0)
        for i in range(count)
    ]

    latencies = np.empty(count, dtype=np.int64)
    t_start = time.perf_counter_ns()
    for i in range(count):
        t0 = time.perf_counter_ns()
        process(buy_orders[i])
        t1 = time.perf_counter_ns()
        latencies[i] = t1 - t0
    t_end = time.perf_counter_ns()

    elapsed_sec = (t_end - t_start) / 1e9
    stats = calculate_distribution(latencies)
    stats.update({
        "name": "Partial-Fill Execution",
        "count": count,
        "elapsed_sec": elapsed_sec,
        "throughput_ops": count / elapsed_sec if elapsed_sec > 0 else 0.0,
        "trades_executed": lob.total_trades_executed,
    })
    return stats


def benchmark_multi_level_matching(count: int = 5000, levels: int = 5) -> Dict[str, Any]:
    """Measure multi-level matching latency (sweeping across multiple price levels)."""
    lob = LimitOrderBook(tick_size=0.01)
    process = lob.process_order

    latencies = np.empty(count, dtype=np.int64)

    t_start = time.perf_counter_ns()
    for run_i in range(count):
        # Insert resting asks across levels
        base_id = run_i * (levels + 1) * 2
        for lvl in range(levels):
            process(Order(order_id=base_id + lvl, price=100.00 + (lvl * 0.01), quantity=10, side=Side.SELL, timestamp_ns=0))

        # Sweep order across all levels
        sweep_order = Order(
            order_id=base_id + levels + 1,
            price=100.00 + (levels * 0.01),
            quantity=10 * levels,
            side=Side.BUY,
            timestamp_ns=0
        )

        t0 = time.perf_counter_ns()
        process(sweep_order)
        t1 = time.perf_counter_ns()
        latencies[run_i] = t1 - t0

    t_end = time.perf_counter_ns()
    elapsed_sec = (t_end - t_start) / 1e9
    stats = calculate_distribution(latencies)
    stats.update({
        "name": f"Multi-Level Sweep ({levels} Levels)",
        "count": count,
        "elapsed_sec": elapsed_sec,
        "throughput_ops": count / elapsed_sec if elapsed_sec > 0 else 0.0,
        "sweeps_detected": getattr(lob, "total_sweeps_detected", 0),
    })
    return stats


def benchmark_continuous_workload(order_count: int = 100000, seed: int = 42) -> Dict[str, Any]:
    """Measure continuous matching engine throughput and latency distribution on realistic order stream."""
    cfg = OrderGeneratorConfig(
        initial_order_id=1000001,
        total_orders=order_count,
        min_price=95.00,
        max_price=105.00,
        buy_ratio=0.50,
        seed=seed,
    )
    generator = OrderGenerator(cfg)
    orders = generator.generate_batch(order_count)

    lob = LimitOrderBook(tick_size=0.01)
    warmup_engine(lob, min(5000, order_count // 10))
    lob = LimitOrderBook(tick_size=0.01)

    process = lob.process_order
    latencies = np.empty(order_count, dtype=np.int64)

    t_start = time.perf_counter_ns()
    for i in range(order_count):
        order = orders[i]
        t0 = time.perf_counter_ns()
        process(order)
        t1 = time.perf_counter_ns()
        latencies[i] = t1 - t0
    t_end = time.perf_counter_ns()

    elapsed_sec = (t_end - t_start) / 1e9
    stats = calculate_distribution(latencies)
    stats.update({
        "name": f"Continuous Realistic Workload ({order_count:,} orders)",
        "count": order_count,
        "elapsed_sec": elapsed_sec,
        "throughput_ops": order_count / elapsed_sec if elapsed_sec > 0 else 0.0,
        "trades_executed": lob.total_trades_executed,
        "volume_executed": lob.total_volume_executed,
        "sweeps_detected": getattr(lob, "total_sweeps_detected", 0),
        "engine_mode": "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON",
    })
    return stats


def print_benchmark_table(results: List[Dict[str, Any]]):
    """Pretty-print benchmark results table."""
    print("\n" + "=" * 90)
    print(f"{'BENCHMARK SCENARIO':<34} | {'ORDERS':>8} | {'THROUGHPUT':>12} | {'MEAN':>7} | {'P50':>6} | {'P95':>6} | {'P99':>6}")
    print(f"{'':<34} | {'':>8} | {'(orders/s)':>12} | {'(us)':>7} | {'(us)':>6} | {'(us)':>6} | {'(us)':>6}")
    print("-" * 90)
    for r in results:
        print(
            f"{r['name']:<34} | {r['count']:>8,} | {r['throughput_ops']:>12,.1f} | "
            f"{r['mean_us']:>7.2f} | {r['p50_us']:>6.2f} | {r['p95_us']:>6.2f} | {r['p99_us']:>6.2f}"
        )
    print("=" * 90 + "\n")


def run_all_engine_benchmarks(workload_sizes: List[int] = None) -> List[Dict[str, Any]]:
    if workload_sizes is None:
        workload_sizes = [10_000, 100_000, 1_000_000]

    all_results = []
    print("\n" + "#" * 70)
    print("CHRONOSMATCH MATCHING ENGINE FORMAL BENCHMARK SUITE")
    print(f"Engine Implementation: {'CYTHON NATIVE' if IS_NATIVE_CYTHON else 'PURE PYTHON FALLBACK'}")
    print("#" * 70)

    # 1. Specialized Micro-Benchmarks
    print("\n--> Running Scenario 1: Order Insertion Latency (10,000 orders)...")
    res1 = benchmark_order_insertion(10_000)
    all_results.append(res1)

    print("--> Running Scenario 2: BUY Order Matching Latency (10,000 orders)...")
    res2 = benchmark_buy_matching(10_000)
    all_results.append(res2)

    print("--> Running Scenario 3: SELL Order Matching Latency (10,000 orders)...")
    res3 = benchmark_sell_matching(10_000)
    all_results.append(res3)

    print("--> Running Scenario 4: Partial-Fill Execution Latency (10,000 orders)...")
    res4 = benchmark_partial_fill(10_000)
    all_results.append(res4)

    print("--> Running Scenario 5: Multi-Level Sweep Latency (5,000 sweeps, 5 levels)...")
    res5 = benchmark_multi_level_matching(5_000, levels=5)
    all_results.append(res5)

    # 2. Realistic Continuous Workloads
    for n in workload_sizes:
        print(f"--> Running Scenario 6: Continuous Workload ({n:,} orders)...")
        res6 = benchmark_continuous_workload(n)
        all_results.append(res6)

    print_benchmark_table(all_results)
    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChronosMatch Matching Engine Formal Benchmark")
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 100000, 1000000],
                        help="Workload sizes for continuous benchmark (default: 10000 100000 1000000)")
    args = parser.parse_args()
    run_all_engine_benchmarks(args.sizes)
