import pytest

from ipc.structures import ORDER_SIZE, Order, Side, pack_order, unpack_order


@pytest.mark.parametrize(
    ("side", "expected_side"),
    [
        ("buy", Side.BUY),
        ("B", Side.BUY),
        ("sell", Side.SELL),
        ("S", Side.SELL),
    ],
)
def test_order_side_strings_are_normalized(side, expected_side):
    order = Order(
        order_id=1,
        price=100.0,
        quantity=5,
        side=side,
        timestamp_ns=123,
    )

    assert order.side == expected_side
    assert order.side_name == expected_side.name


def test_pack_order_uses_fixed_size_and_round_trips():
    original = Order(
        order_id=17,
        price=99.75,
        quantity=12,
        side=Side.SELL,
        timestamp_ns=987654321,
    )

    payload = pack_order(original)
    restored = unpack_order(payload)

    assert len(payload) == ORDER_SIZE
    assert restored == original


def test_invalid_order_side_is_rejected():
    with pytest.raises(ValueError, match="Invalid order side"):
        Order(order_id=1, price=100.0, quantity=1, side="hold")
