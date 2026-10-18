"""Measure in-memory ring-buffer order production throughput."""

import argparse
import asyncio
import time

from ipc.ring_buffer import RingBuffer
from ipc.structures import ORDER_SIZE
from simulator.market_simulator import MarketSimulator


def benchmark(order_count: int) -> tuple[int, float]:
    """Return the number of produced orders and production time in seconds."""
    if order_count <= 0:
        raise ValueError("order_count must be positive")

    with RingBuffer(capacity=order_count, slot_size=ORDER_SIZE) as ring:
        simulator = MarketSimulator(ring, seed=42)
        started_at = time.perf_counter()
        written = asyncio.run(simulator.produce(order_count))
        elapsed = time.perf_counter() - started_at

        if written != order_count:
            raise RuntimeError(
                f"Expected to produce {order_count} orders, wrote {written}"
            )

        for _ in range(written):
            if ring.read() is None:
                raise RuntimeError("Ring buffer became empty before all orders were read")

    return written, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark ChronosMatch ring-buffer order production"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100_000,
        help="number of orders to generate (default: 100000)",
    )
    args = parser.parse_args()

    if args.count <= 0:
        parser.error("--count must be positive")

    written, elapsed = benchmark(args.count)
    print(f"Orders produced: {written}")
    print(f"Production time: {elapsed:.6f} seconds")
    print(f"Production throughput: {written / elapsed:,.0f} orders/second")


if __name__ == "__main__":
    main()
