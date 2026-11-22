from ipc.structures import (
    Order,
    Side,
    ORDER_SIZE,
    pack_order,
    unpack_order,
)


def test_order_pack_and_unpack():
    order = Order(101, 250.50, 10, Side.BUY, 123456789)
    data = pack_order(order)
    restored = unpack_order(data)

    assert len(data) == ORDER_SIZE
    assert restored.order_id == 101
    assert restored.price == 250.50
    assert restored.quantity == 10
    assert restored.side == Side.BUY
    assert restored.timestamp_ns == 123456789


def test_sell_order():
    order = Order(102, 251.75, 20, Side.SELL, 987654321)
    restored = unpack_order(pack_order(order))

    assert restored.side_name == "SELL"
