"""Concurrent producer-consumer IPC latency benchmark."""

import asyncio
import statistics
import time

from ipc.ring_buffer import RingBuffer
from ipc.structures import ORDER_SIZE, Order, Side, pack_order, unpack_order


async def run_latency_test(total_orders=100_000):
    ring = RingBuffer(capacity=2048, slot_size=ORDER_SIZE)
    latencies_us = []
    consumed = 0

    async def producer():
        for order_id in range(1, total_orders + 1):
            order = Order(
                order_id=order_id,
                price=100.0,
                quantity=10,
                side=Side.BUY,
            )
            payload = pack_order(order)

            while not ring.write(payload):
                await asyncio.sleep(0)

            if order_id % 100 == 0:
                await asyncio.sleep(0)

    async def consumer():
        nonlocal consumed

        while consumed < total_orders:
            data = ring.read()

            if data is None:
                await asyncio.sleep(0)
                continue

            received = unpack_order(data)
            latency_us = (
                time.time_ns() - received.timestamp_ns
            ) / 1_000

            latencies_us.append(latency_us)
            consumed += 1

    try:
        start = time.perf_counter()

        await asyncio.gather(producer(), consumer())

        elapsed = time.perf_counter() - start

        print("\nCONCURRENT IPC LATENCY RESULTS")
        print("--------------------------------")
        print(f"Orders produced:  {total_orders:,}")
        print(f"Orders consumed:  {consumed:,}")
        print(f"Elapsed time:     {elapsed:.3f} seconds")
        print(f"Throughput:       {consumed / elapsed:,.0f} orders/sec")
        print(f"Average latency:  {statistics.mean(latencies_us):.2f} microseconds")
        print(f"Median latency:   {statistics.median(latencies_us):.2f} microseconds")
        print(f"P95 latency:      {statistics.quantiles(latencies_us, n=100)[94]:.2f} microseconds")
        print(f"Maximum latency:  {max(latencies_us):.2f} microseconds")

    finally:
        ring.close()


if __name__ == "__main__":
    asyncio.run(run_latency_test())