"""
ChronosMatch End-to-End Trading Pipeline & Execution Engine (Week 2)
Integrates:
    Market Simulator -> IPC Ring Buffer -> Consumer Worker -> Matching Engine -> Dashboard

Pipeline Flow:
    1. Market Simulator generates mock BUY/SELL orders.
    2. Orders are packed into 29-byte binary struct (<QdIBQ).
    3. Simulator writes packed data into shared-memory RingBuffer.
    4. Consumer coroutine drains orders from RingBuffer with zero-loss guarantee.
    5. Deserialized orders enter the LimitOrderBook with Price-Time Priority.
    6. Executed trades and top-of-book depth update the real-time Curses Dashboard.
"""

import asyncio
import time
import argparse
import sys
from typing import Optional, List

from ipc.structures import Order, unpack_order, ORDER_SIZE
from ipc.ring_buffer import RingBuffer
from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from core.models import Trade
from simulator.market_simulator import run_simulator, SimulatorStats
from simulator.order_generator import OrderGeneratorConfig
from monitoring.dashboard import OrderBookDashboard, HAVE_CURSES


class ChronosEngine:
    """
    Coordinates the asynchronous ingestion, matching, and monitoring pipeline.
    """

    def __init__(
        self,
        ring_buffer: RingBuffer,
        lob: Optional[LimitOrderBook] = None,
        batch_size: int = 500,
    ):
        self.ring_buffer = ring_buffer
        self.lob = lob or LimitOrderBook()
        self.batch_size = max(1, batch_size)
        self.is_running = False

        # Consumer statistics
        self.orders_consumed = 0
        self.trades_generated = 0
        self.consumer_elapsed_sec = 0.0

    async def run_consumer(self, stop_event: asyncio.Event) -> int:
        """
        Continuously drain packed orders from the RingBuffer and execute matching.

        Args:
            stop_event: Signal set by producer when all orders have been submitted.

        Returns:
            Total count of orders matched.
        """
        self.is_running = True
        rb_read = self.ring_buffer.read
        process_order = self.lob.process_order
        unpack = unpack_order
        batch_size = self.batch_size

        t0 = time.perf_counter()

        while not stop_event.is_set():
            batch_count = 0
            while batch_count < batch_size:
                data = rb_read()
                if data is None:
                    break
                order = unpack(data)
                trades = process_order(order)
                self.orders_consumed += 1
                self.trades_generated += len(trades)
                batch_count += 1

            if batch_count == 0:
                # Yield to event loop to allow simulator to produce
                await asyncio.sleep(0)

        # Final drain of remaining orders in the ring buffer
        while True:
            data = rb_read()
            if data is None:
                break
            order = unpack(data)
            trades = process_order(order)
            self.orders_consumed += 1
            self.trades_generated += len(trades)

        self.consumer_elapsed_sec = max(1e-9, time.perf_counter() - t0)
        self.is_running = False
        return self.orders_consumed

    async def start_pipeline(
        self,
        total_orders: int = 100_000,
        target_rate: Optional[int] = 100_000,
        with_dashboard: bool = False,
        seed: Optional[int] = 42,
    ) -> dict:
        """
        Launch the end-to-end simulation, ingestion, matching, and monitoring pipeline.
        """
        stop_event = asyncio.Event()

        # 1. Start Consumer Worker Task
        consumer_task = asyncio.create_task(self.run_consumer(stop_event))

        # 2. Optionally start curses dashboard task
        dashboard_task = None
        dashboard = None
        if with_dashboard and HAVE_CURSES:
            dashboard = OrderBookDashboard(self.lob, refresh_hz=10.0)
            dashboard_task = asyncio.create_task(dashboard.render_loop_async(stop_event))

        # 3. Run Market Simulator producer
        sim_stats = await run_simulator(
            ring_buffer=self.ring_buffer,
            total_orders=total_orders,
            target_orders_per_sec=target_rate,
            batch_size=self.batch_size,
            backpressure_mode="wait",
            seed=seed,
        )

        # 4. Signal consumer and dashboard to finish
        stop_event.set()
        await consumer_task

        if dashboard_task:
            if dashboard:
                dashboard.is_running = False
            await dashboard_task

        consumer_throughput = self.orders_consumed / self.consumer_elapsed_sec

        return {
            "orders_generated": sim_stats.orders_generated,
            "orders_written": sim_stats.orders_written,
            "orders_consumed": self.orders_consumed,
            "trades_generated": self.trades_generated,
            "producer_elapsed": sim_stats.elapsed_time,
            "consumer_elapsed": self.consumer_elapsed_sec,
            "producer_throughput": sim_stats.throughput_ops,
            "consumer_throughput": consumer_throughput,
            "dropped": sim_stats.orders_dropped,
            "retries": sim_stats.orders_retried,
            "mode": "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON FALLBACK",
        }


def parse_args():
    parser = argparse.ArgumentParser(
        description="ChronosMatch End-to-End Trading Engine & Simulator Pipeline"
    )
    parser.add_argument(
        "--orders", type=int, default=100_000, help="Total orders to simulate (default: 100,000)"
    )
    parser.add_argument(
        "--rate", type=int, default=0, help="Target ingestion rate (0 = unthrottled maximum)"
    )
    parser.add_argument(
        "--buffer-capacity", type=int, default=131_072, help="Ring buffer capacity (default: 131,072)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Orders per batch yield (default: 500)"
    )
    parser.add_argument(
        "--dashboard", action="store_true", help="Launch real-time curses terminal dashboard"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducible order stream (default: 42)"
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    target_rate = args.rate if args.rate > 0 else None

    print("\n" + "=" * 60)
    print("      CHRONOSMATCH ZERO-COPY TRADING ENGINE PIPELINE")
    print("=" * 60)
    print(f"Engine Mode:        {'CYTHON NATIVE' if IS_NATIVE_CYTHON else 'PURE PYTHON FALLBACK'}")
    print(f"Simulated Orders:   {args.orders:,}")
    print(f"Target Rate:        {target_rate or 'MAX UNTHROTTLED'}")
    print(f"Buffer Capacity:    {args.buffer_capacity:,} slots")
    print(f"Terminal Dashboard: {'ENABLED' if args.dashboard else 'DISABLED (Headless)'}")
    print("=" * 60 + "\n")

    ring_buffer = RingBuffer(capacity=args.buffer_capacity, slot_size=ORDER_SIZE)
    lob = LimitOrderBook()
    engine = ChronosEngine(ring_buffer=ring_buffer, lob=lob, batch_size=args.batch_size)

    results = await engine.start_pipeline(
        total_orders=args.orders,
        target_rate=target_rate,
        with_dashboard=args.dashboard,
        seed=args.seed,
    )

    ring_buffer.close()

    print("\n" + "=" * 60)
    print("                PIPELINE EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Orders Generated:     {results['orders_generated']:,}")
    print(f"Orders Written (IPC): {results['orders_written']:,}")
    print(f"Orders Consumed:      {results['orders_consumed']:,}")
    print(f"Trades Executed:      {results['trades_generated']:,}")
    print(f"Producer Elapsed:     {results['producer_elapsed']:.4f} sec")
    print(f"Consumer Elapsed:     {results['consumer_elapsed']:.4f} sec")
    print(f"Producer Throughput:  {results['producer_throughput']:,.1f} orders/sec")
    print(f"Consumer Throughput:  {results['consumer_throughput']:,.1f} orders/sec")
    print(f"Dropped Orders:       {results['dropped']}")
    print(f"Backpressure Retries: {results['retries']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
