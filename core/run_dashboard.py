"""
ChronosMatch Standalone Dashboard Runner (Week 2)
Launches the integrated simulator, IPC ring buffer, Cython matching engine, and curses dashboard.

Usage:
    python -m core.run_dashboard --orders 100000 --rate 50000
    python run_dashboard.py --orders 50000
"""

import sys
import os
import argparse
import asyncio
import signal

from ipc.structures import ORDER_SIZE
from ipc.ring_buffer import RingBuffer
from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from core.engine import ChronosEngine
from monitoring.dashboard import OrderBookDashboard, HAVE_CURSES


def parse_args():
    parser = argparse.ArgumentParser(
        description="ChronosMatch: Real-Time Matching Engine & Terminal Dashboard"
    )
    parser.add_argument(
        "--orders",
        type=int,
        default=50_000,
        help="Total orders to simulate (default: 50,000)",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=25_000,
        help="Target orders per second (default: 25,000 ops/s; 0 = unthrottled maximum)",
    )
    parser.add_argument(
        "--buffer-capacity",
        type=int,
        default=131_072,
        help="Ring buffer capacity in slots (default: 131,072)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Orders per batch yield (default: 500)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible order generation (default: 42)",
    )
    parser.add_argument(
        "--refresh-hz",
        type=float,
        default=10.0,
        help="Dashboard UI refresh rate in Hz (default: 10.0)",
    )
    parser.add_argument(
        "--auto-exit",
        action="store_true",
        help="Automatically exit dashboard upon simulation completion (default: False)",
    )
    return parser.parse_args()


async def run():
    args = parse_args()

    if not HAVE_CURSES:
        print("[Error] Python 'curses' is required. On Windows, ensure 'windows-curses' is installed.")
        sys.exit(1)

    target_rate = args.rate if args.rate > 0 else None
    is_interactive = sys.stdout.isatty()
    if not is_interactive:
        print("[Notice] Non-interactive or redirected terminal detected. Executing pipeline in console mode.")
        print("[Notice] For full interactive curses dashboard, execute directly in an interactive terminal window.")

    # Setup IPC ring buffer and matching engine
    ring_buffer = RingBuffer(capacity=args.buffer_capacity, slot_size=ORDER_SIZE)
    lob = LimitOrderBook()
    engine = ChronosEngine(ring_buffer=ring_buffer, lob=lob, batch_size=args.batch_size)

    try:
        results = await engine.start_pipeline(
            total_orders=args.orders,
            target_rate=target_rate,
            with_dashboard=is_interactive,
            seed=args.seed,
            auto_exit=args.auto_exit,
        )

        print("\n" + "=" * 60)
        print("          CHRONOSMATCH DASHBOARD SESSION SUMMARY")
        print("=" * 60)
        print(f"Engine Mode:           {results['mode']}")
        print(f"Orders Ingested:       {results['orders_consumed']:,}")
        print(f"Trades Executed:       {results['trades_generated']:,}")
        print(f"Producer Throughput:   {results['producer_throughput']:,.1f} orders/sec")
        print(f"Consumer Throughput:   {results['consumer_throughput']:,.1f} orders/sec")
        print(f"Engine Latency (Mean): {results['match_latency_mean_us']:.2f} us")
        print(f"Engine Latency (P95):  {results['match_latency_p95_us']:.2f} us")
        print(f"Engine Latency (P99):  {results['match_latency_p99_us']:.2f} us")
        print(f"E2E Latency (Mean):    {results['e2e_latency_mean_us']:.2f} us")
        print(f"E2E Latency (P95):     {results['e2e_latency_p95_us']:.2f} us")
        print(f"E2E Latency (P99):     {results['e2e_latency_p99_us']:.2f} us")
        print(f"Dropped Orders:        {results['dropped']}")
        print("=" * 60 + "\n")

    finally:
        ring_buffer.close()


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[Shutdown] ChronosMatch interrupted by user.")
    except Exception as e:
        print(f"\n[Error] {e}")


if __name__ == "__main__":
    main()
