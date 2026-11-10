
"""Initialize the shared ChronosMatch ring buffer."""

import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, PROJECT_ROOT)

from ipc.ring_buffer import RingBuffer


BUFFER_PATH = os.path.join(os.path.dirname(__file__), "shared_buffer.dat")


def main():
    ring = RingBuffer(
        capacity=2048,
        filepath=BUFFER_PATH,
        create=True,
    )

    try:
        ring.flush()
        print("Shared buffer initialized successfully.")
        print(f"Buffer location: {BUFFER_PATH}")
        print("Capacity: 2048 orders")
    finally:
        ring.close()


if __name__ == "__main__":
    main()
