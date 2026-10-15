from ipc.structures import ORDER_SIZE, Order, Side, pack_order, unpack_order


def test_order_round_trip_preserves_fields():
    original = Order(
        order_id=123,
        price=100.25,
        quantity=7,
        side=Side.BUY,
        timestamp_ns=987654321,
    )

    payload = pack_order(original)
    decoded = unpack_order(payload)

    assert ORDER_SIZE == 29
    assert len(payload) == 29
    assert decoded.order_id == original.order_id
    assert decoded.price == original.price
    assert decoded.quantity == original.quantity
    assert decoded.side == original.side
    assert decoded.timestamp_ns == original.timestamp_ns
