"""Simple asynchronous market-order generator for ChronosMatch."""

import argparse
import asyncio
import random

from ipc.ring_buffer import RingBuffer
from ipc.structures import Order, Side, ORDER_SIZE, pack_order


class MarketSimulator:
    def __init__(self, buffer: RingBuffer, *, start_order_id: int = 1, seed: int | None = None):
        self.buffer = buffer
        self.next_order_id = start_order_id
        self.random = random.Random(seed)

    def make_order(self) -> bytes:
        """Generate and serialize one 29-byte order."""
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
        """Write up to count orders and return the number written."""
        if count < 0:
            raise ValueError("count must not be negative")
        if full_sleep < 0:
            raise ValueError("full_sleep must not be negative")

        written = 0
        while written < count:
            payload = self.make_order()

            while not self.buffer.write(payload):
                if not wait_when_full:
                    return written
                await asyncio.sleep(full_sleep)

            written += 1
            await asyncio.sleep(0)

        return written


async def demo(path: str, capacity: int, count: int) -> None:
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    if count < 0:
        raise ValueError("count must not be negative")
    if count > capacity:
        raise ValueError("count cannot exceed capacity in demo mode")

    buffer = RingBuffer(
        capacity=capacity,
        slot_size=ORDER_SIZE,
        filepath=path,
        create=True,
    )
    try:
        simulator = MarketSimulator(buffer, seed=42)
        written = await simulator.produce(count)
        print(f"Generated and wrote {written} orders to {path}")
        print(f"Orders remaining in buffer: {buffer.size()}")
    finally:
        buffer.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="ChronosMatch market simulator")
    parser.add_argument("--path", default="chronosmatch.mmap")
    parser.add_argument("--capacity", type=int, default=1024)
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()

    if args.capacity <= 0:
        parser.error("--capacity must be positive")
    if args.count < 0:
        parser.error("--count must not be negative")
    if args.count > args.capacity:
        parser.error("--count cannot exceed --capacity in demo mode")

    asyncio.run(demo(args.path, args.capacity, args.count))


if __name__ == "__main__":
    main()
