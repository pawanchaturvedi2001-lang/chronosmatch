"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
Market Simulator module (Member 3)

Coordinates the high-throughput asynchronous generation and streaming of mock orders
into the shared-memory Ring Buffer via zero-copy struct packing.

Architecture flow:
    asyncio simulator -> Order -> pack_order() -> RingBuffer.write() -> mmap IPC
"""

import asyncio
import time
import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from ipc.structures import Order, pack_order, ORDER_SIZE
from ipc.ring_buffer import RingBuffer
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig


@dataclass
class SimulatorStats:
    """
    Performance and operational metrics tracked by the Market Simulator.
    """
    orders_generated: int = 0
    orders_written: int = 0
    orders_dropped: int = 0
    orders_retried: int = 0
    failed_writes: int = 0
    elapsed_time: float = 0.0
    throughput_ops: float = 0.0
    throughput_history: List[Dict[str, Any]] = field(default_factory=list)

    def print_summary(self):
        """Prints a human-readable performance summary."""
        print("\n" + "=" * 50)
        print("ChronosMatch Market Simulator Benchmark Summary")
        print("=" * 50)
        print(f"Orders generated: {self.orders_generated:,}")
        print(f"Orders written:   {self.orders_written:,}")
        print(f"Elapsed:          {self.elapsed_time:.4f} sec")
        print(f"Throughput:       {self.throughput_ops:,.2f} orders/sec")
        print(f"Dropped:          {self.orders_dropped:,}")
        print(f"Retries:          {self.orders_retried:,}")
        print(f"Failed writes:    {self.failed_writes:,}")
        print("=" * 50)


class MarketSimulator:
    """
    Asynchronous Market Simulator engine.

    Streams synthetic orders through binary packing into the shared memory Ring Buffer.
    Handles backpressure through either lossless wait/retry (correctness mode)
    or lossy drop tracking (benchmark mode).
    """

    def __init__(
        self,
        ring_buffer: RingBuffer,
        config: Optional[OrderGeneratorConfig] = None,
        batch_size: int = 500,
        backpressure_mode: str = "wait",
        retry_backoff: float = 0.0,
    ):
        """
        Initialize the Market Simulator.

        Args:
            ring_buffer: Target IPC RingBuffer instance.
            config: Configuration for order parameters and target rates.
            batch_size: Number of orders processed per event loop yield batch.
            backpressure_mode: 'wait' for lossless wait/retry (default),
                               'drop' for dropping orders when buffer is full.
            retry_backoff: Sleep duration (in seconds) during backpressure retries
                           (0.0 yields via asyncio.sleep(0)).
        """
        self.ring_buffer = ring_buffer
        self.config = config or OrderGeneratorConfig()
        self.batch_size = max(1, batch_size)
        self.backpressure_mode = backpressure_mode.lower().strip()
        if self.backpressure_mode not in ("wait", "drop"):
            raise ValueError(f"Invalid backpressure_mode: {backpressure_mode}. Choose 'wait' or 'drop'.")
        self.retry_backoff = retry_backoff
        self.generator = OrderGenerator(self.config)
        self._is_running = False
        self.stats = SimulatorStats()

    def stop(self):
        """Signal the simulator to stop generation."""
        self._is_running = False

    async def run(self) -> SimulatorStats:
        """
        Execute the simulation loop asynchronously.

        Returns:
            SimulatorStats containing complete metrics from the run.
        """
        self._is_running = True
        self.stats = SimulatorStats()
        stats = self.stats

        target_rate = self.config.target_orders_per_sec
        total_target = self.config.total_orders

        # Local bindings for fast loop execution
        rb = self.ring_buffer
        write_method = rb.write
        gen_order = self.generator.generate_order
        has_next = self.generator.has_next
        pack = pack_order
        batch_size = self.batch_size
        mode_wait = (self.backpressure_mode == "wait")
        retry_sleep = self.retry_backoff

        start_time = time.perf_counter()
        last_interval_time = start_time
        last_interval_written = 0

        try:
            while self._is_running and has_next():
                # Process in batches to balance event loop cooperativeness and peak throughput
                count = 0
                while count < batch_size and has_next():
                    order = gen_order()
                    stats.orders_generated += 1
                    data = pack(order)

                    # Attempt ring buffer write
                    written = write_method(data)
                    if written:
                        stats.orders_written += 1
                        count += 1
                    else:
                        if mode_wait:
                            # Correctness mode: backpressure wait and retry until space is available
                            stats.orders_retried += 1
                            while self._is_running and not written:
                                await asyncio.sleep(retry_sleep)
                                written = write_method(data)
                                if written:
                                    stats.orders_written += 1
                                    count += 1
                                else:
                                    stats.orders_retried += 1
                        else:
                            # Drop mode: record drop for backpressure benchmark analysis
                            stats.orders_dropped += 1
                            stats.failed_writes += 1
                            count += 1

                # Rate limiting and cooperative yielding
                now = time.perf_counter()
                elapsed = now - start_time

                # Periodic history tracking (every ~0.5 sec)
                if now - last_interval_time >= 0.5:
                    delta_orders = stats.orders_written - last_interval_written
                    delta_time = now - last_interval_time
                    interval_rate = delta_orders / delta_time if delta_time > 0 else 0.0
                    stats.throughput_history.append({
                        "elapsed": elapsed,
                        "orders_written": stats.orders_written,
                        "interval_rate": interval_rate,
                    })
                    last_interval_time = now
                    last_interval_written = stats.orders_written

                # Target rate pacing (if specified)
                if target_rate and target_rate > 0:
                    expected_time = stats.orders_written / target_rate
                    ahead_by = expected_time - elapsed
                    if ahead_by > 0.001:
                        await asyncio.sleep(ahead_by)
                    else:
                        # Yield to let other tasks run without unnecessary timer delay
                        await asyncio.sleep(0)
                else:
                    # Unthrottled mode: yield cooperatively
                    await asyncio.sleep(0)

        except asyncio.CancelledError:
            pass
        finally:
            end_time = time.perf_counter()
            self._is_running = False
            stats.elapsed_time = max(1e-9, end_time - start_time)
            stats.throughput_ops = stats.orders_written / stats.elapsed_time

        return stats


async def run_simulator(
    ring_buffer: RingBuffer,
    total_orders: int = 100_000,
    target_orders_per_sec: Optional[int] = 100_000,
    batch_size: int = 500,
    backpressure_mode: str = "wait",
    config: Optional[OrderGeneratorConfig] = None,
    **kwargs,
) -> SimulatorStats:
    """
    High-level entry point to run the market simulator.

    Args:
        ring_buffer: Target RingBuffer for IPC orders.
        total_orders: Total orders to blast.
        target_orders_per_sec: Rate throttle (None for unthrottled maximum).
        batch_size: Orders per event loop iteration.
        backpressure_mode: 'wait' (default, lossless) or 'drop' (benchmark).
        config: Optional pre-configured OrderGeneratorConfig.
        kwargs: Overrides for OrderGeneratorConfig fields.

    Returns:
        SimulatorStats with throughput and order metrics.
    """
    if config is None:
        cfg = OrderGeneratorConfig(
            total_orders=total_orders,
            target_orders_per_sec=target_orders_per_sec,
            **kwargs,
        )
    else:
        cfg = config
        if total_orders is not None:
            cfg.total_orders = total_orders
        if target_orders_per_sec is not None:
            cfg.target_orders_per_sec = target_orders_per_sec

    simulator = MarketSimulator(
        ring_buffer=ring_buffer,
        config=cfg,
        batch_size=batch_size,
        backpressure_mode=backpressure_mode,
    )
    return await simulator.run()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ChronosMatch Market Simulator - Blast mock orders into IPC Ring Buffer"
    )
    parser.add_argument(
        "--orders", type=int, default=100_000, help="Total orders to generate (default: 100,000)"
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=100_000,
        help="Target orders per second (default: 100,000; set 0 for unthrottled)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size per event loop yield (default: 500)",
    )
    parser.add_argument(
        "--buffer-capacity",
        type=int,
        default=131072,
        help="Ring buffer slot capacity (default: 131,072 slots)",
    )
    parser.add_argument(
        "--backpressure",
        choices=["wait", "drop"],
        default="wait",
        help="Backpressure mode when buffer is full (default: 'wait')",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for deterministic order stream"
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    target_rate = args.rate if args.rate > 0 else None

    print("Initializing IPC RingBuffer...")
    ring_buf = RingBuffer(capacity=args.buffer_capacity, slot_size=ORDER_SIZE)

    print(
        f"Starting Market Simulator: {args.orders:,} orders, "
        f"target rate: {target_rate or 'MAX'} orders/sec, "
        f"backpressure: {args.backpressure}..."
    )

    stats = await run_simulator(
        ring_buffer=ring_buf,
        total_orders=args.orders,
        target_orders_per_sec=target_rate,
        batch_size=args.batch_size,
        backpressure_mode=args.backpressure,
        seed=args.seed,
    )

    stats.print_summary()
    ring_buf.close()


if __name__ == "__main__":
    asyncio.run(main())
