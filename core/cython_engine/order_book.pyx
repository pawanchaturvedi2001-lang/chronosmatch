# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: initializedcheck=False

"""
ChronosMatch Cython-Optimized Limit Order Book (LOB)
Native C-extension implementing Price-Time Priority matching with static C typing.

Hot-path matching is accelerated using C integers, floats, and pointers,
while isolating pure-C math into nogil routines.
"""

from libc.stdint cimport uint64_t, uint32_t, uint8_t, int64_t
from libc.math cimport round as c_round
import heapq
import time
from collections import deque

from ipc.structures import Order, Side
from core.models import Trade, PriceLevel


cdef inline int64_t c_price_to_ticks(double price, double inv_tick) nogil:
    """Convert floating-point price to integer ticks without GIL."""
    return <int64_t>(c_round(price * inv_tick))


cdef inline double c_ticks_to_price(int64_t ticks, double tick_size) nogil:
    """Convert integer ticks to floating-point price without GIL."""
    return <double>(ticks) * tick_size


cdef inline uint32_t c_min_qty(uint32_t a, uint32_t b) nogil:
    """Fast C min without GIL."""
    return a if a < b else b


cdef class LimitOrderBook:
    """
    Cython-accelerated Limit Order Book with Price-Time Priority.
    """

    cdef public double tick_size
    cdef double _inv_tick
    cdef public bint self_trade_prevention

    cdef list _bid_heap
    cdef dict _bids
    cdef list _ask_heap
    cdef dict _asks
    cdef dict _orders_by_id

    cdef public uint64_t _trade_counter
    cdef object _recent_trades

    cdef public uint64_t total_orders_processed
    cdef public uint64_t total_trades_executed
    cdef public uint64_t total_volume_executed
    cdef public int64_t last_match_latency_ns
    cdef public int64_t total_match_latency_ns

    def __init__(self, double tick_size=0.01, bint self_trade_prevention=True):
        self.tick_size = tick_size
        self._inv_tick = 1.0 / tick_size
        self.self_trade_prevention = self_trade_prevention

        self._bid_heap = []
        self._bids = {}
        self._ask_heap = []
        self._asks = {}
        self._orders_by_id = {}

        self._trade_counter = 0
        self._recent_trades = deque(maxlen=100)

        self.total_orders_processed = 0
        self.total_trades_executed = 0
        self.total_volume_executed = 0
        self.last_match_latency_ns = 0
        self.total_match_latency_ns = 0

    cdef inline int64_t _to_ticks(self, double price) nogil:
        return c_price_to_ticks(price, self._inv_tick)

    cdef inline double _to_price(self, int64_t ticks) nogil:
        return c_ticks_to_price(ticks, self.tick_size)

    cdef void _clean_best_bid(self):
        cdef int64_t tick
        while self._bid_heap:
            tick = -self._bid_heap[0]
            q = self._bids.get(tick)
            if q is not None and len(q) > 0:
                break
            heapq.heappop(self._bid_heap)
            if tick in self._bids:
                del self._bids[tick]

    cdef void _clean_best_ask(self):
        cdef int64_t tick
        while self._ask_heap:
            tick = self._ask_heap[0]
            q = self._asks.get(tick)
            if q is not None and len(q) > 0:
                break
            heapq.heappop(self._ask_heap)
            if tick in self._asks:
                del self._asks[tick]

    cpdef object get_best_bid(self):
        """Returns (best_bid_price, aggregate_quantity) or None."""
        cdef int64_t best_tick
        cdef uint32_t total_qty = 0
        self._clean_best_bid()
        if not self._bid_heap:
            return None
        best_tick = -self._bid_heap[0]
        q = self._bids[best_tick]
        for o in q:
            total_qty += <uint32_t>o.quantity
        return (round(self._to_price(best_tick), 4), total_qty)

    cpdef object get_best_ask(self):
        """Returns (best_ask_price, aggregate_quantity) or None."""
        cdef int64_t best_tick
        cdef uint32_t total_qty = 0
        self._clean_best_ask()
        if not self._ask_heap:
            return None
        best_tick = self._ask_heap[0]
        q = self._asks[best_tick]
        for o in q:
            total_qty += <uint32_t>o.quantity
        return (round(self._to_price(best_tick), 4), total_qty)

    cpdef object get_spread(self):
        """Returns best_ask - best_bid or None if one side is empty."""
        bb = self.get_best_bid()
        ba = self.get_best_ask()
        if bb is None or ba is None:
            return None
        return round(ba[0] - bb[0], 4)

    cpdef tuple get_depth(self, int levels=5):
        """Returns top N bid levels and ask levels."""
        self._clean_best_bid()
        self._clean_best_ask()

        cdef list bids_depth = []
        cdef list asks_depth = []
        cdef int64_t tick
        cdef uint32_t qty

        sorted_bids = sorted(self._bids.keys(), reverse=True)
        for tick in sorted_bids:
            q = self._bids.get(tick)
            if q is not None and len(q) > 0:
                qty = 0
                for o in q:
                    qty += <uint32_t>o.quantity
                bids_depth.append(PriceLevel(
                    price=round(self._to_price(tick), 4),
                    total_quantity=qty,
                    order_count=len(q)
                ))
                if len(bids_depth) >= levels:
                    break

        sorted_asks = sorted(self._asks.keys())
        for tick in sorted_asks:
            q = self._asks.get(tick)
            if q is not None and len(q) > 0:
                qty = 0
                for o in q:
                    qty += <uint32_t>o.quantity
                asks_depth.append(PriceLevel(
                    price=round(self._to_price(tick), 4),
                    total_quantity=qty,
                    order_count=len(q)
                ))
                if len(asks_depth) >= levels:
                    break

        return (bids_depth, asks_depth)

    cpdef list get_recent_trades(self, int limit=20):
        """Returns recent executed trades."""
        trades = list(self._recent_trades)
        return trades[-limit:] if limit > 0 else trades

    cpdef bint cancel_order(self, uint64_t order_id):
        """Cancel a resting order by order ID."""
        cdef tuple entry = self._orders_by_id.pop(order_id, None)
        if entry is None:
            return False

        cdef int64_t ticks = entry[0]
        cdef uint8_t side = entry[1]
        cdef object target_order = entry[2]
        cdef dict target_dict = self._bids if side == Side.BUY else self._asks

        q = target_dict.get(ticks)
        if q is not None:
            try:
                q.remove(target_order)
                return True
            except ValueError:
                pass
        return False

    cpdef add_resting_order(self, object order):
        """Insert order directly as resting order without matching."""
        cdef double price = <double>order.price
        cdef int64_t ticks = self._to_ticks(price)
        cdef uint8_t side = <uint8_t>order.side
        cdef uint64_t order_id = <uint64_t>order.order_id

        if side == Side.BUY:
            if ticks not in self._bids or len(self._bids[ticks]) == 0:
                self._bids[ticks] = deque()
                heapq.heappush(self._bid_heap, -ticks)
            self._bids[ticks].append(order)
        else:
            if ticks not in self._asks or len(self._asks[ticks]) == 0:
                self._asks[ticks] = deque()
                heapq.heappush(self._ask_heap, ticks)
            self._asks[ticks].append(order)

        self._orders_by_id[order_id] = (ticks, side, order)

    cpdef list process_order(self, object order):
        """
        Execute Price-Time Priority matching for an incoming order.
        """
        cdef int64_t t0 = time.perf_counter_ns()
        self.total_orders_processed += 1
        cdef list trades = []

        cdef uint32_t quantity = <uint32_t>order.quantity
        if quantity <= 0:
            return trades

        cdef uint64_t order_id = <uint64_t>order.order_id
        cdef double order_price = <double>order.price
        cdef uint8_t order_side = <uint8_t>order.side
        cdef uint64_t order_ts = <uint64_t>order.timestamp_ns
        cdef int64_t order_ticks = self._to_ticks(order_price)
        cdef uint32_t remaining_qty = quantity
        cdef uint32_t matched_qty
        cdef double exec_price
        cdef int64_t best_ask_tick
        cdef int64_t best_bid_tick
        cdef object ask_queue
        cdef object bid_queue
        cdef object resting_ask
        cdef object resting_bid
        cdef uint64_t resting_id
        cdef uint32_t resting_qty
        cdef object trade
        cdef object residual_order
        cdef int64_t t1
        cdef int64_t latency
        now_ns = time.time_ns

        if order_side == Side.BUY:
            while remaining_qty > 0:
                self._clean_best_ask()
                if not self._ask_heap:
                    break

                best_ask_tick = self._ask_heap[0]
                if order_ticks < best_ask_tick:
                    break

                ask_queue = self._asks[best_ask_tick]
                while ask_queue and remaining_qty > 0:
                    resting_ask = ask_queue[0]
                    resting_id = <uint64_t>resting_ask.order_id

                    if self.self_trade_prevention and resting_id == order_id:
                        break

                    resting_qty = <uint32_t>resting_ask.quantity
                    matched_qty = c_min_qty(remaining_qty, resting_qty)
                    exec_price = round(self._to_price(best_ask_tick), 4)

                    self._trade_counter += 1
                    trade = Trade(
                        trade_id=self._trade_counter,
                        price=exec_price,
                        quantity=matched_qty,
                        buy_order_id=order_id,
                        sell_order_id=resting_id,
                        timestamp_ns=now_ns(),
                    )
                    trades.append(trade)
                    self._recent_trades.append(trade)

                    self.total_trades_executed += 1
                    self.total_volume_executed += matched_qty
                    remaining_qty -= matched_qty

                    if resting_qty == matched_qty:
                        ask_queue.popleft()
                        self._orders_by_id.pop(resting_id, None)
                    else:
                        resting_ask.quantity = resting_qty - matched_qty
                        break

                if not ask_queue:
                    heapq.heappop(self._ask_heap)
                    del self._asks[best_ask_tick]

        else:
            while remaining_qty > 0:
                self._clean_best_bid()
                if not self._bid_heap:
                    break

                best_bid_tick = -self._bid_heap[0]
                if order_ticks > best_bid_tick:
                    break

                bid_queue = self._bids[best_bid_tick]
                while bid_queue and remaining_qty > 0:
                    resting_bid = bid_queue[0]
                    resting_id = <uint64_t>resting_bid.order_id

                    if self.self_trade_prevention and resting_id == order_id:
                        break

                    resting_qty = <uint32_t>resting_bid.quantity
                    matched_qty = c_min_qty(remaining_qty, resting_qty)
                    exec_price = round(self._to_price(best_bid_tick), 4)

                    self._trade_counter += 1
                    trade = Trade(
                        trade_id=self._trade_counter,
                        price=exec_price,
                        quantity=matched_qty,
                        buy_order_id=resting_id,
                        sell_order_id=order_id,
                        timestamp_ns=now_ns(),
                    )
                    trades.append(trade)
                    self._recent_trades.append(trade)

                    self.total_trades_executed += 1
                    self.total_volume_executed += matched_qty
                    remaining_qty -= matched_qty

                    if resting_qty == matched_qty:
                        bid_queue.popleft()
                        self._orders_by_id.pop(resting_id, None)
                    else:
                        resting_bid.quantity = resting_qty - matched_qty
                        break

                if not bid_queue:
                    heapq.heappop(self._bid_heap)
                    del self._bids[best_bid_tick]

        if remaining_qty > 0:
            residual_order = Order(
                order_id=order_id,
                price=order_price,
                quantity=remaining_qty,
                side=order_side,
                timestamp_ns=order_ts,
            )
            self.add_resting_order(residual_order)

        t1 = time.perf_counter_ns()
        latency = t1 - t0
        self.last_match_latency_ns = latency
        self.total_match_latency_ns += latency

        return trades
