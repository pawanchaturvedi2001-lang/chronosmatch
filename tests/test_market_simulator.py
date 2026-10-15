import asyncio

from ipc.ring_buffer import RingBuffer
from ipc.structures import ORDER_SIZE, Side, unpack_order
from simulator.market_simulator import MarketSimulator


def test_produce_writes_orders():
    with RingBuffer(capacity=2, slot_size=ORDER_SIZE) as ring:
        simulator = MarketSimulator(ring, seed=42)

        assert asyncio.run(simulator.produce(2)) == 2

        orders = [unpack_order(ring.read()) for _ in range(2)]
        assert [order.order_id for order in orders] == [1, 2]
        assert all(order.side in (Side.BUY, Side.SELL) for order in orders)


def test_nonblocking_produce_does_not_consume_order_id_when_full():
    with RingBuffer(capacity=1, slot_size=ORDER_SIZE) as ring:
        simulator = MarketSimulator(ring, start_order_id=7, seed=42)
        assert ring.write(simulator.make_order())

        assert asyncio.run(
            simulator.produce(1, wait_when_full=False)
        ) == 0

        ring.read()
        assert asyncio.run(simulator.produce(1, wait_when_full=False)) == 1
        order = ring.read()
        assert order is not None
        assert unpack_order(order).order_id == 8
