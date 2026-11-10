
"""Compare single-record and batch ring-buffer performance."""

import time

from ipc.ring_buffer import RingBuffer
from ipc.structures import ORDER_SIZE, Order, Side, pack_order


TOTAL_ORDERS = 100_000
BATCH_SIZE = 64


def make_records():
    return [
        pack_order(
            Order(
                order_id=i,
                price=100.0,
                quantity=10,
                side=Side.BUY,
            )
        )
        for i in range(1, TOTAL_ORDERS + 1)
    ]


def benchmark_single(records):
    ring = RingBuffer(capacity=2048, slot_size=ORDER_SIZE)

    try:
        start = time.perf_counter()

        for record in records:
            while not ring.write(record):
                pass

            while ring.read() is None:
                pass

        elapsed = time.perf_counter() - start

        return elapsed, TOTAL_ORDERS / elapsed

    finally:
        ring.close()


def benchmark_batch(records):
    ring = RingBuffer(capacity=2048, slot_size=ORDER_SIZE)

    try:
        start = time.perf_counter()

        for start_index in range(0, len(records), BATCH_SIZE):
            batch = records[start_index:start_index + BATCH_SIZE]

            written = 0
            while written < len(batch):
                written += ring.write_many(batch[written:])

            received = []
            while len(received) < len(batch):
                received.extend(
                    ring.read_many(len(batch) - len(received))
                )

        elapsed = time.perf_counter() - start

        return elapsed, TOTAL_ORDERS / elapsed

    finally:
        ring.close()


def main():
    print(f"Preparing {TOTAL_ORDERS:,} orders...")
    records = make_records()

    print("\nRunning single-record benchmark...")
    single_time, single_rate = benchmark_single(records)

    print("Running batch benchmark...")
    batch_time, batch_rate = benchmark_batch(records)

    improvement = batch_rate / single_rate

    print("\nRING BUFFER PERFORMANCE COMPARISON")
    print("----------------------------------")
    print(f"Orders tested:       {TOTAL_ORDERS:,}")
    print(f"Batch size:          {BATCH_SIZE}")
    print(f"Single time:         {single_time:.4f} seconds")
    print(f"Batch time:          {batch_time:.4f} seconds")
    print(f"Single throughput:   {single_rate:,.0f} orders/sec")
    print(f"Batch throughput:    {batch_rate:,.0f} orders/sec")
    print(f"Throughput ratio:    {improvement:.2f}x")


if __name__ == "__main__":
    main()
