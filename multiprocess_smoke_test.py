import os
import tempfile
from multiprocessing import Process

from ipc.structures import Order, pack_order, unpack_order
from ipc.ring_buffer import RingBuffer


def producer(filepath):
    buffer = RingBuffer(capacity=128, filepath=filepath, create=False)
    try:
        for i in range(100):
            order = Order(
                order_id=i + 1,
                price=100.0 + i,
                quantity=i + 1,
                side="BUY" if i % 2 == 0 else "SELL",
                timestamp_ns=1000000 + i
            )
            if not buffer.write(pack_order(order)):
                raise RuntimeError(f"Buffer full at order {i + 1}")
    finally:
        buffer.close()


def main():
    fd, path = tempfile.mkstemp(prefix="chronosmatch_ipc_", suffix=".mmap")
    os.close(fd)

    initializer = RingBuffer(capacity=128, filepath=path, create=True)
    initializer.close()

    reader = None

    try:
        process = Process(target=producer, args=(path,))
        process.start()
        process.join(timeout=15)

        if process.is_alive():
            process.terminate()
            process.join()
            raise RuntimeError("Producer timed out")

        if process.exitcode != 0:
            raise RuntimeError(f"Producer failed with exit code {process.exitcode}")

        reader = RingBuffer(capacity=128, filepath=path, create=False)
        received_ids = []

        while not reader.is_empty():
            payload = reader.read()
            if payload is None:
                break
            received_ids.append(unpack_order(payload).order_id)

        expected_ids = list(range(1, 101))

        assert received_ids == expected_ids, (
            f"Order mismatch: received {len(received_ids)} orders"
        )

        print("PASS: Separate-process mmap IPC test")
        print(f"Orders sent: 100")
        print(f"Orders received: {len(received_ids)}")
        print("Missing or duplicate orders: 0")

    finally:
        if reader is not None:
            reader.close()
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    main()
