"""Consumer process for the ChronosMatch shared ring buffer."""

import os
import sys
import time

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, PROJECT_ROOT)

from ipc.ring_buffer import RingBuffer
from ipc.structures import unpack_order
from process_lock import NamedMutex


BUFFER_PATH = os.path.join(
    os.path.dirname(__file__), "shared_buffer.dat"
)
EXPECTED_ORDERS = 1000


def main():
    ring = RingBuffer(
        capacity=2048,
        filepath=BUFFER_PATH,
        create=False,
    )

    mutex = NamedMutex()

    try:
        consumed = 0
        deadline = time.monotonic() + 60

        print("Consumer started. Waiting for orders...")

        while consumed < EXPECTED_ORDERS:
            with mutex:
                payload = ring.read()

            if payload is None:
                if time.monotonic() > deadline:
                    print("Timed out waiting for orders.")
                    break

                time.sleep(0.001)
                continue

            order = unpack_order(payload)
            consumed += 1

            if consumed <= 5:
                print(
                    f"Read order {order.order_id}: "
                    f"price={order.price}, "
                    f"quantity={order.quantity}, "
                    f"side={order.side_name}"
                )

        print(f"\nConsumer read {consumed} orders.")

    finally:
        mutex.close()
        ring.close()


if __name__ == "__main__":
    main()