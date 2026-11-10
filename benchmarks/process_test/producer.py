
"""Producer process for the ChronosMatch shared ring buffer."""

import os
import sys
import time

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, PROJECT_ROOT)

from ipc.ring_buffer import RingBuffer
from ipc.structures import Order, pack_order
from process_lock import NamedMutex


BUFFER_PATH = os.path.join(
    os.path.dirname(__file__), "shared_buffer.dat"
)

ORDER_COUNT = 1000


def main():
    # Open the already initialized shared buffer.
    ring = RingBuffer(
        capacity=2048,
        filepath=BUFFER_PATH,
        create=False,
    )

    mutex = NamedMutex()

    try:
        written = 0

        for i in range(ORDER_COUNT):

            # Create an order.
            order = Order(
                order_id=i + 1,
                price=10000.0,
                quantity=10,
                side=1,
            )

            # Convert the order into binary format.
            payload = pack_order(order)

            # Write the order safely into the shared buffer.
            while True:
                with mutex:
                    success = ring.write(payload)

                if success:
                    break

                time.sleep(0.001)

            written += 1

            # Slow down slightly so the consumer can read concurrently.
            time.sleep(0.01)

        ring.flush()

        print(f"Producer wrote {written} orders.")

    finally:
        mutex.close()
        ring.close()


if __name__ == "__main__":
    main()
