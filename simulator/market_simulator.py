"""Asynchronous market simulator for ChronosMatch."""

import argparse
import asyncio
import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from ipc.ring_buffer import RingBuffer
from ipc.structures import Order, Side, ORDER_SIZE, pack_order
from simulator.order_generator import OrderGenerator, OrderGeneratorConfig


@dataclass
class SimulatorStats:
    """Performance and operational metrics for a simulator run."""

    orders_generated: int = 0
    orders_written: int = 0
    orders_dropped: int = 0
    orders_retried: int = 0
    failed_writes: int = 0
    elapsed_time: float = 0.0
    throughput_ops: float = 0.0
    throughput_history: List[Dict[str, Any]] = field(default_factory=list)

    def print_summary(self):
        """Print a summary of the simulation."""
        print("\n" + "=" * 50)
        print("ChronosMatch Market Simulator Summary")
        print("=" * 50)
        print(f"Orders generated: {self.orders_generated:,}")
        print(f"Orders written:   {self.orders_written:,}")
        print(f"Orders dropped:   {self.orders_dropped:,}")
        print(f"Orders retried:   {self.orders_retried:,}")
        print(f"Failed writes:    {self.failed_writes:,}")
        print(f"Elapsed time:     {self.elapsed_time:.4f} sec")
        print(f"Throughput:       {self.throughput_ops:,.2f} orders/sec")
        print("=" * 50)


class MarketSimulator:
    """Generate orders and write them to a shared ring buffer."""

    def __init__(
        self,
        ring_buffer: RingBuffer,
        config: Optional[OrderGeneratorConfig] = None,
        batch_size: int = 500,
        backpressure_mode: str = "wait",
        retry_backoff: float = 0.0,
        *,
        start_order_id: int = 1,
        seed: Optional[int] = None,
    ):
        self.buffer = ring_buffer
        self.ring_buffer = ring_buffer

        self.config = config or OrderGeneratorConfig(seed=seed)
        self.batch_size = max(1, batch_size)

        self.backpressure_mode = backpressure_mode.lower().strip()
        if self.backpressure_mode not in ("wait", "drop"):
            raise ValueError(
                "backpressure_mode must be 'wait' or 'drop'"
            )

        if retry_backoff < 0:
            raise ValueError("retry_backoff must not be negative")

        self.retry_backoff = retry_backoff
        self.generator = OrderGenerator(self.config)
        self.stats = SimulatorStats()
        self._is_running = False

        # These fields preserve the original Member 2 API.
        self.next_order_id = start_order_id
        self.random = random.Random(seed)

    def make_order(self) -> bytes:
        """Generate and serialize one order using the original Member 2 API."""
        order = Order(
            order_id=self.next_order_id,
            price=round(self.random.uniform(99.0, 101.0), 2),
            quantity=self.random.randint(1, 100),
            side=self.random.choice((Side.BUY, Side.SELL)),
        )
        self.next_order_id += 1
        return pack_order(order)

    async def produce(
        self,
        count: int,
        *,
        wait_when_full: bool = True,
        full_sleep: float = 0.0001,
    ) -> int:
        """Write up to count orders using the original Member 2 API."""
        if count < 0:
            raise ValueError("count must not be negative")
        if full_sleep < 0:
            raise ValueError("full_sleep must not be negative")

        written = 0

        while written < count:
            if self.buffer.is_full():
                if not wait_when_full:
                    return written
                await asyncio.sleep(full_sleep)
                continue

            # Save the generator state so a failed nonblocking write
            # does not consume an order ID or change the random sequence.
            saved_order_id = self.next_order_id
            saved_random_state = self.random.getstate()
            payload = self.make_order()

            if self.buffer.write(payload):
                written += 1
            else:
                self.next_order_id = saved_order_id
                self.random.setstate(saved_random_state)

                if not wait_when_full:
                    return written

                await asyncio.sleep(full_sleep)
                continue

            await asyncio.sleep(0)

        return written

    def stop(self):
        """Ask the asynchronous simulation loop to stop."""
        self._is_running = False

    async def run(self) -> SimulatorStats:
        """Generate configured orders and write them to the ring buffer."""
        self._is_running = True
        self.stats = SimulatorStats()

        stats = self.stats
        target_rate = self.config.target_orders_per_sec
        ring_write = self.ring_buffer.write
        generate_order = self.generator.generate_order
        has_next = self.generator.has_next

        start_time = time.perf_counter()
        last_interval_time = start_time
        last_interval_written = 0

        try:
            while self._is_running and has_next():
                processed = 0

                while (
                    self._is_running
                    and has_next()
                    and processed < self.batch_size
                ):
                    order = generate_order()
                    stats.orders_generated += 1
                    payload = pack_order(order)

                    written = ring_write(payload)

                    if not written and self.backpressure_mode == "wait":
                        while self._is_running and not written:
                            stats.orders_retried += 1
                            await asyncio.sleep(self.retry_backoff)
                            written = ring_write(payload)

                    if written:
                        stats.orders_written += 1
                    elif self.backpressure_mode == "drop":
                        stats.orders_dropped += 1
                        stats.failed_writes += 1

                    processed += 1

                now = time.perf_counter()
                elapsed = now - start_time

                if now - last_interval_time >= 0.5:
                    delta_orders = (
                        stats.orders_written - last_interval_written
                    )
                    delta_time = now - last_interval_time

                    stats.throughput_history.append({
                        "elapsed": elapsed,
                        "orders_written": stats.orders_written,
                        "interval_rate": (
                            delta_orders / delta_time
                            if delta_time > 0 else 0.0
                        ),
                    })

                    last_interval_time = now
                    last_interval_written = stats.orders_written

                if target_rate and target_rate > 0:
                    expected_time = stats.orders_written / target_rate
                    ahead_by = expected_time - elapsed

                    if ahead_by > 0.001:
                        await asyncio.sleep(ahead_by)
                    else:
                        await asyncio.sleep(0)
                else:
                    await asyncio.sleep(0)

        except asyncio.CancelledError:
            raise
        finally:
            self._is_running = False
            stats.elapsed_time = max(
                1e-9, time.perf_counter() - start_time
            )
            stats.throughput_ops = (
                stats.orders_written / stats.elapsed_time
            )

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
    """Convenience function for running a configured market simulation."""

    if config is None:
        cfg = OrderGeneratorConfig(
            total_orders=total_orders,
            target_orders_per_sec=target_orders_per_sec,
            **kwargs,
        )
    else:
        cfg = replace(config)

        if total_orders is not None:
            cfg.total_orders = total_orders

        if target_orders_per_sec is not None:
            cfg.target_orders_per_sec = target_orders_per_sec

        for key, value in kwargs.items():
            if not hasattr(cfg, key):
                raise TypeError(f"Unknown order generator option: {key}")
            setattr(cfg, key, value)

    simulator = MarketSimulator(
        ring_buffer=ring_buffer,
        config=cfg,
        batch_size=batch_size,
        backpressure_mode=backpressure_mode,
    )

    return await simulator.run()


def parse_args():
    """Read command-line options."""
    parser = argparse.ArgumentParser(
        description="ChronosMatch Market Simulator"
    )
    parser.add_argument(
        "--orders", "--count",
        dest="orders",
        type=int,
        default=100_000,
        help="Number of orders to generate",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=100_000,
        help="Target orders per second; use 0 for unthrottled",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--buffer-capacity", "--capacity",
        dest="buffer_capacity",
        type=int,
        default=131072,
    )
    parser.add_argument(
        "--backpressure",
        choices=["wait", "drop"],
        default="wait",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--path", default=None)
    return parser.parse_args()


async def main():
    """Run the simulator from the command line."""
    args = parse_args()

    if args.orders < 0:
        raise SystemExit("--orders must not be negative")
    if args.buffer_capacity <= 0:
        raise SystemExit("--buffer-capacity must be positive")

    target_rate = args.rate if args.rate > 0 else None

    ring_buffer = RingBuffer(
        capacity=args.buffer_capacity,
        slot_size=ORDER_SIZE,
        filepath=args.path,
        create=True,
    )

    try:
        stats = await run_simulator(
            ring_buffer=ring_buffer,
            total_orders=args.orders,
            target_orders_per_sec=target_rate,
            batch_size=args.batch_size,
            backpressure_mode=args.backpressure,
            seed=args.seed,
        )
        stats.print_summary()
    finally:
        ring_buffer.close()


if __name__ == "__main__":
    asyncio.run(main())