"""
ChronosMatch Formal IPC Benchmarks (Phase 5)
Measures:
1. Producer Throughput (binary pack + ring buffer write)
2. Consumer Throughput (ring buffer read + binary unpack)
3. IPC Transit / Transfer Latency (queue wait time per slot)
4. Buffer-Full Handling Overhead & Backpressure (constrained vs standard capacity)
5. Multi-Process Producer/Consumer Throughput & Latency across independent processes

Uses the existing mmap-backed RingBuffer implementation.
All timing uses time.perf_counter_ns() and time.perf_counter().
Percentiles (P50, P90, P95, P99) and statistics are reported in microseconds (us).
"""

import sys
import os
import time
import argparse
import tempfile
import multiprocessing as mp
from pathlib import Path
from typing import Dict, Any, List
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ipc.structures import Order, Side, pack_order, unpack_order, ORDER_SIZE, ORDER_STRUCT
from ipc.ring_buffer import RingBuffer
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig


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


def benchmark_raw_producer_consumer(order_count: int = 100_000) -> Dict[str, Any]:
    """Measure single-process raw write and read throughput in shared memory without contention."""
    cap = order_count + 1024
    rb = RingBuffer(capacity=cap, slot_size=ORDER_SIZE)

    # Pre-generate orders
    cfg = OrderGeneratorConfig(initial_order_id=1, total_orders=order_count, seed=42)
    gen = OrderGenerator(cfg)
    orders = gen.generate_batch(order_count)

    write_latencies = np.empty(order_count, dtype=np.int64)
    read_latencies = np.empty(order_count, dtype=np.int64)

    # 1. Producer write phase
    write = rb.write
    pack = pack_order
    t0_write = time.perf_counter()
    for i in range(order_count):
        order = orders[i]
        t0 = time.perf_counter_ns()
        data = pack(order)
        write(data)
        t1 = time.perf_counter_ns()
        write_latencies[i] = t1 - t0
    t1_write = time.perf_counter()
    write_elapsed = max(1e-9, t1_write - t0_write)

    # 2. Consumer read phase
    read = rb.read
    unpack = unpack_order
    t0_read = time.perf_counter()
    for i in range(order_count):
        t0 = time.perf_counter_ns()
        data = read()
        order = unpack(data)
        t1 = time.perf_counter_ns()
        read_latencies[i] = t1 - t0
    t1_read = time.perf_counter()
    read_elapsed = max(1e-9, t1_read - t0_read)

    rb.close()

    w_stats = calculate_distribution(write_latencies)
    r_stats = calculate_distribution(read_latencies)

    return {
        "order_count": order_count,
        "write_elapsed_sec": write_elapsed,
        "write_throughput": order_count / write_elapsed,
        "write_mean_us": w_stats["mean_us"],
        "write_p50_us": w_stats["p50_us"],
        "write_p95_us": w_stats["p95_us"],
        "write_p99_us": w_stats["p99_us"],
        "read_elapsed_sec": read_elapsed,
        "read_throughput": order_count / read_elapsed,
        "read_mean_us": r_stats["mean_us"],
        "read_p50_us": r_stats["p50_us"],
        "read_p95_us": r_stats["p95_us"],
        "read_p99_us": r_stats["p99_us"],
    }


def _producer_worker_task(filepath: str, capacity: int, target_orders: int, done_event, stop_event, q_out):
    try:
        rb = RingBuffer(capacity=capacity, filepath=filepath, create=False)
        pack = ORDER_STRUCT.pack
        write = rb.write
        perf_ns = time.perf_counter_ns

        t_start = time.perf_counter_ns()
        retries = 0

        for i in range(target_orders):
            side = 1 if (i % 2 == 0) else 2
            price = 95.0 + ((i % 200) * 0.05)
            qty = 5 + (i % 96)
            ts = perf_ns()
            payload = pack(1000000 + i, price, qty, side, ts)

            spins = 0
            while not write(payload):
                retries += 1
                if stop_event.is_set():
                    break
                spins += 1
                if spins < 32:
                    pass
                elif spins < 256:
                    time.sleep(0)
                else:
                    time.sleep(0.0001)

            if stop_event.is_set():
                break

        t_end = time.perf_counter_ns()
        rb.close()
        done_event.set()

        duration_s = max(1e-9, (t_end - t_start) / 1e9)
        q_out.put({
            "status": "SUCCESS",
            "duration_s": duration_s,
            "retries": retries,
            "throughput_ops": target_orders / duration_s,
        })
    except Exception as e:
        done_event.set()
        q_out.put({"status": "ERROR", "error": str(e)})


def _consumer_worker_task(filepath: str, capacity: int, target_orders: int, done_event, stop_event, q_out):
    try:
        rb = RingBuffer(capacity=capacity, filepath=filepath, create=False)
        unpack = ORDER_STRUCT.unpack
        read = rb.read
        perf_ns = time.perf_counter_ns

        sample_stride = max(1, target_orders // 20000)
        sample_latencies = []

        t_start = time.perf_counter_ns()
        received = 0

        while received < target_orders:
            raw = read()
            if raw is not None:
                now_ns = perf_ns()
                order_id, price, qty, side, ts = unpack(raw)
                if (received % sample_stride == 0) and ts > 0:
                    lat = now_ns - ts
                    if lat >= 0:
                        sample_latencies.append(lat)
                received += 1
            else:
                if stop_event.is_set():
                    break
                if done_event.is_set() and rb.is_empty():
                    break
                time.sleep(0)

        t_end = time.perf_counter_ns()
        rb.close()

        duration_s = max(1e-9, (t_end - t_start) / 1e9)
        q_out.put({
            "status": "SUCCESS",
            "duration_s": duration_s,
            "received": received,
            "throughput_ops": received / duration_s,
            "latencies_ns": sample_latencies,
        })
    except Exception as e:
        q_out.put({"status": "ERROR", "error": str(e)})


def benchmark_multiprocess_ipc(order_count: int = 100_000, buffer_capacity: int = 65536) -> Dict[str, Any]:
    """Measure true cross-process IPC throughput, queue transit latency, and backpressure."""
    fd, mmap_path = tempfile.mkstemp(prefix="chronos_ipc_bench_", suffix=".mmap")
    os.close(fd)

    init_rb = RingBuffer(capacity=buffer_capacity, slot_size=ORDER_SIZE, filepath=mmap_path, create=True)
    init_rb.close()

    done_event = mp.Event()
    stop_event = mp.Event()
    prod_q = mp.Queue()
    cons_q = mp.Queue()

    p_cons = mp.Process(
        target=_consumer_worker_task,
        args=(mmap_path, buffer_capacity, order_count, done_event, stop_event, cons_q),
    )
    p_prod = mp.Process(
        target=_producer_worker_task,
        args=(mmap_path, buffer_capacity, order_count, done_event, stop_event, prod_q),
    )

    t_wall_start = time.perf_counter()
    p_cons.start()
    p_prod.start()

    timeout = max(15.0, 15.0 + (order_count / 30000.0))
    p_prod.join(timeout=timeout)
    if p_prod.is_alive():
        stop_event.set()
        p_prod.terminate()
        p_prod.join(timeout=2.0)

    p_cons.join(timeout=max(5.0, timeout / 2.0))
    if p_cons.is_alive():
        stop_event.set()
        p_cons.terminate()
        p_cons.join(timeout=2.0)

    t_wall_end = time.perf_counter()
    wall_elapsed = max(1e-9, t_wall_end - t_wall_start)

    prod_res = prod_q.get(timeout=5.0) if not prod_q.empty() else {"status": "TIMEOUT", "retries": 0, "duration_s": 0.0}
    cons_res = cons_q.get(timeout=5.0) if not cons_q.empty() else {"status": "TIMEOUT", "latencies_ns": []}

    try:
        if os.path.exists(mmap_path):
            os.remove(mmap_path)
    except Exception:
        pass

    latencies_ns = np.array(cons_res.get("latencies_ns", []), dtype=np.int64)
    stats = calculate_distribution(latencies_ns)

    return {
        "order_count": order_count,
        "buffer_capacity": buffer_capacity,
        "wall_elapsed_sec": wall_elapsed,
        "wall_throughput": order_count / wall_elapsed,
        "prod_elapsed_sec": prod_res.get("duration_s", 0.0),
        "prod_throughput": prod_res.get("throughput_ops", 0.0),
        "cons_elapsed_sec": cons_res.get("duration_s", 0.0),
        "cons_throughput": cons_res.get("throughput_ops", 0.0),
        "retries": prod_res.get("retries", 0),
        "transit_mean_us": stats["mean_us"],
        "transit_p50_us": stats["p50_us"],
        "transit_p90_us": stats["p90_us"],
        "transit_p95_us": stats["p95_us"],
        "transit_p99_us": stats["p99_us"],
        "transit_max_us": stats["max_us"],
    }


def run_all_ipc_benchmarks() -> Dict[str, Any]:
    print("\n" + "#" * 70)
    print("CHRONOSMATCH INTER-PROCESS COMMUNICATION (IPC) BENCHMARKS")
    print("#" * 70, flush=True)

    # 1. Raw write and read speed
    print("\n[1/3] Measuring Raw Single-Process Write & Read Throughput (100,000 orders)...", flush=True)
    raw_res = benchmark_raw_producer_consumer(100_000)
    print(f"  Producer: {raw_res['write_throughput']:,.1f} orders/sec | Mean: {raw_res['write_mean_us']:.2f} us | P95: {raw_res['write_p95_us']:.2f} us", flush=True)
    print(f"  Consumer: {raw_res['read_throughput']:,.1f} orders/sec | Mean: {raw_res['read_mean_us']:.2f} us | P95: {raw_res['read_p95_us']:.2f} us", flush=True)

    # 2. Buffer-full handling & backpressure overhead
    print("\n[2/3] Measuring Backpressure Overhead (Constrained Buffer: 2,048 slots vs 100,000 orders)...", flush=True)
    bp_res = benchmark_multiprocess_ipc(order_count=100_000, buffer_capacity=2048)
    print(f"  Constrained Throughput: {bp_res['wall_throughput']:,.1f} orders/sec | Retries: {bp_res['retries']:,}", flush=True)
    print(f"  Transit Latency: Mean: {bp_res['transit_mean_us']:.2f} us | P50: {bp_res['transit_p50_us']:.2f} us | P95: {bp_res['transit_p95_us']:.2f} us | P99: {bp_res['transit_p99_us']:.2f} us", flush=True)

    # 3. Multi-process cross-process scaling: 10k, 100k, 1M orders
    print("\n[3/3] Measuring Cross-Process IPC (Standard Capacity: 65,536 slots)...", flush=True)
    mp_results = []
    for count in [10_000, 100_000, 1_000_000]:
        print(f"  --> Benchmarking {count:,} orders across independent processes...", flush=True)
        res = benchmark_multiprocess_ipc(order_count=count, buffer_capacity=65536)
        mp_results.append(res)
        print(f"      Wall Throughput: {res['wall_throughput']:,.1f} orders/sec | Producer: {res['prod_throughput']:,.1f} ops/s | Consumer: {res['cons_throughput']:,.1f} ops/s", flush=True)
        print(f"      Transit Latency: Mean {res['transit_mean_us']:.2f} us | P50 {res['transit_p50_us']:.2f} us | P95 {res['transit_p95_us']:.2f} us | P99 {res['transit_p99_us']:.2f} us", flush=True)

    print("\n" + "=" * 96, flush=True)
    print(f"{'IPC BENCHMARK STAGE':<32} | {'ORDERS':>9} | {'WALL OPS/S':>12} | {'MEAN':>7} | {'P50':>6} | {'P95':>6} | {'P99':>6}", flush=True)
    print(f"{'':<32} | {'':>9} | {'':>12} | {'(us)':>7} | {'(us)':>6} | {'(us)':>6} | {'(us)':>6}", flush=True)
    print("-" * 96, flush=True)
    for r in mp_results:
        print(
            f"Multi-Process IPC ({r['order_count']:,}) {'':<5} | {r['order_count']:>9,} | {r['wall_throughput']:>12,.1f} | "
            f"{r['transit_mean_us']:>7.2f} | {r['transit_p50_us']:>6.2f} | {r['transit_p95_us']:>6.2f} | {r['transit_p99_us']:>6.2f}",
            flush=True,
        )
    print("=" * 96 + "\n", flush=True)

    return {
        "raw": raw_res,
        "backpressure": bp_res,
        "multiprocess": mp_results,
    }


if __name__ == "__main__":
    mp.freeze_support()
    run_all_ipc_benchmarks()
