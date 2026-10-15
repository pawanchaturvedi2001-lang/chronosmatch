"""Minimal consumer for the ChronosMatch ring buffer."""

from ipc.ring_buffer import RingBuffer
from ipc.structures import unpack_order


def consume_orders(ring_buffer: RingBuffer, max_orders: int | None = None):
    """Read queued binary orders and return decoded Order objects."""
    if max_orders is not None and max_orders < 0:
        raise ValueError("max_orders must be non-negative or None")

    orders = []

    while max_orders is None or len(orders) < max_orders:
        payload = ring_buffer.read()

        if payload is None:
            break

        orders.append(unpack_order(payload))

    return orders
