
import os
import tempfile
from multiprocessing import Process, Queue

from ipc.ring_buffer import RingBuffer
from ipc.structures import Order, pack_order, unpack_order


def producer(path, result_queue):
    try:
        buf = RingBuffer(capacity=256, filepath=path, create=False)
        try:
            result_queue.put(("header", buf.capacity, buf.slot_size))
            order = Order(1, 100.0, 5, "BUY", 123)
            result_queue.put(("write", buf.write(pack_order(order))))
        finally:
            buf.close()
    except Exception as exc:
        result_queue.put(("error", repr(exc)))


if __name__ == "__main__":
    fd, path = tempfile.mkstemp(suffix=".mmap")
    os.close(fd)

    buf = RingBuffer(capacity=256, filepath=path, create=True)
    buf.close()

    q = Queue()
    p = Process(target=producer, args=(path, q))

    try:
        p.start()
        p.join(10)

        if p.is_alive():
            p.terminate()
            p.join()
            print("FAIL: Producer timed out")
        else:
            print("Producer exit code:", p.exitcode)
            while not q.empty():
                print("Producer result:", q.get())

        reader = RingBuffer(capacity=256, filepath=path, create=False)
        try:
            payload = reader.read()
            if payload:
                print("Recovered:", unpack_order(payload))
            else:
                print("No order found in shared buffer")
        finally:
            reader.close()
    finally:
        q.close()
        if os.path.exists(path):
            os.remove(path)
