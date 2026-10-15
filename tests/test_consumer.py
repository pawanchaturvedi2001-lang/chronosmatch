from consumer.consumer import consume_orders
from ipc.ring_buffer import RingBuffer
from ipc.structures import Order, Side, ORDER_SIZE, pack_order


def make_payload(order_id, price, quantity, side):
    return pack_order(
        Order(
            order_id=order_id,
            price=price,
            quantity=quantity,
            side=side,
        )
    )


def test_consume_orders_returns_decoded_orders():
    with RingBuffer(capacity=4, slot_size=ORDER_SIZE) as ring:
        ring.write(make_payload(1, 100.5, 10, Side.BUY))
        ring.write(make_payload(2, 101.0, 5, Side.SELL))
        ring.write(make_payload(3, 99.5, 20, Side.BUY))

        orders = consume_orders(ring)

        assert [order.order_id for order in orders] == [1, 2, 3]
        assert [order.side for order in orders] == [
            Side.BUY, Side.SELL, Side.BUY
        ]
        assert [order.quantity for order in orders] == [10, 5, 20]
        assert [order.price for order in orders] == [100.5, 101.0, 99.5]
        assert ring.is_empty()


def test_consume_orders_respects_max_orders():
    with RingBuffer(capacity=4, slot_size=ORDER_SIZE) as ring:
        for order_id in range(1, 4):
            ring.write(make_payload(order_id, 100.0, 1, Side.BUY))

        orders = consume_orders(ring, max_orders=2)

        assert [order.order_id for order in orders] == [1, 2]
        assert ring.size == 1


def test_consume_orders_empty_buffer():
    with RingBuffer(capacity=4, slot_size=ORDER_SIZE) as ring:
        assert consume_orders(ring) == []


def test_consume_orders_zero_maximum():
    with RingBuffer(capacity=4, slot_size=ORDER_SIZE) as ring:
        ring.write(make_payload(1, 100.0, 1, Side.BUY))

        assert consume_orders(ring, max_orders=0) == []
        assert ring.size == 1
