import pytest

from ipc.ring_buffer import RingBuffer
from ipc.structures import ORDER_SIZE, Order, Side, pack_order, unpack_order


def make_order(order_id):
    return pack_order(
        Order(
            order_id=order_id,
            price=100.5,
            quantity=10,
            side=Side.BUY,
            timestamp_ns=123456789,
        )
    )


def test_initial_state():
    with RingBuffer(capacity=3) as ring:
        assert ring.is_empty()
        assert not ring.is_full()
        assert ring.size == 0
        assert ring.available_write == 3
        assert ring.available_read == 0


def test_fifo_order():
    with RingBuffer(capacity=3) as ring:
        for order_id in (1, 2, 3):
            assert ring.write(make_order(order_id))

        for expected_id in (1, 2, 3):
            data = ring.read()
            assert data is not None
            assert unpack_order(data).order_id == expected_id

        assert ring.is_empty()
        assert ring.read() is None


def test_full_buffer():
    with RingBuffer(capacity=2) as ring:
        assert ring.write(make_order(1))
        assert ring.write(make_order(2))
        assert ring.is_full()
        assert not ring.write(make_order(3))


def test_wraparound():
    with RingBuffer(capacity=2) as ring:
        assert ring.write(make_order(1))
        assert ring.write(make_order(2))

        assert unpack_order(ring.read()).order_id == 1
        assert ring.write(make_order(3))
        assert unpack_order(ring.read()).order_id == 2
        assert unpack_order(ring.read()).order_id == 3


def test_invalid_capacity_and_slot_size():
    with pytest.raises(ValueError):
        RingBuffer(capacity=0)

    with pytest.raises(ValueError):
        RingBuffer(capacity=2, slot_size=0)


def test_invalid_record_size():
    with RingBuffer(capacity=2) as ring:
        with pytest.raises(ValueError):
            ring.write(b"short")

        with pytest.raises(ValueError):
            ring.write(b"x" * (ORDER_SIZE + 1))


def test_file_backed_reopen(tmp_path):
    path = str(tmp_path / "orders.mmap")

    with RingBuffer(capacity=3, filepath=path, create=True) as writer:
        assert writer.write(make_order(42))
        writer.flush()

    with RingBuffer(capacity=3, filepath=path, create=False) as reader:
        data = reader.read()
        assert data is not None
        assert unpack_order(data).order_id == 42
