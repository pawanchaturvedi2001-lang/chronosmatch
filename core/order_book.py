"""
ChronosMatch Limit Order Book (LOB) and Matching Engine
Implements strict Price-Time Priority matching.

Provides both pure-Python high-performance implementation and transparent
fallback/wrapper when native Cython extension is compiled.
"""

from collections import deque
import heapq
import time
from typing import Dict, List, Optional, Tuple

from ipc.structures import Order, Side, SIDE_BUY, SIDE_SELL
from core.models import Trade, PriceLevel

# Attempt to import compiled Cython engine
try:
    from core.cython_engine.order_book import LimitOrderBook as CythonLimitOrderBook
    CYTHON_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    CythonLimitOrderBook = None
    CYTHON_AVAILABLE = False


class PyLimitOrderBook:
    """
    Pure-Python Limit Order Book implementing Price-Time Priority matching.

    Price representation:
        Internally scales prices to integer ticks (e.g., cents: 100.50 -> 10050)
        to guarantee strict deterministic sorting without floating-point precision drift.

    Time priority:
        Each price level maintains a FIFO deque of resting orders.
    """

    def __init__(
        self,
        tick_size: float = 0.01,
        self_trade_prevention: bool = True,
    ):
        """
        Initialize the Limit Order Book.

        Args:
            tick_size: Minimum price increment (defaults to 0.01).
            self_trade_prevention: If True, orders cannot trade against the same order ID.
        """
        self.tick_size = tick_size
        self._inv_tick = 1.0 / tick_size
        self.self_trade_prevention = self_trade_prevention

        # Bids: max-heap of negative price ticks (-ticks), mapping to FIFO deque
        self._bid_heap: List[int] = []
        self._bids: Dict[int, deque[Order]] = {}  # ticks -> deque[Order]

        # Asks: min-heap of positive price ticks (+ticks), mapping to FIFO deque
        self._ask_heap: List[int] = []
        self._asks: Dict[int, deque[Order]] = {}  # ticks -> deque[Order]

        # Fast lookup by order_id: maps order_id -> (ticks, Side, Order)
        self._orders_by_id: Dict[int, Tuple[int, int, Order]] = {}

        # Trade history and execution metrics
        self._trade_counter = 0
        self._recent_trades: deque[Trade] = deque(maxlen=100)

        # Operational metrics
        self.total_orders_processed = 0
        self.total_trades_executed = 0
        self.total_volume_executed = 0
        self.last_match_latency_ns = 0
        self.total_match_latency_ns = 0

    def _price_to_ticks(self, price: float) -> int:
        """Convert a floating-point price to integer ticks."""
        return int(round(price * self._inv_tick))

    def _ticks_to_price(self, ticks: int) -> float:
        """Convert integer ticks back to floating-point price."""
        return round(ticks * self.tick_size, 4)

    def _clean_best_bid(self):
        """Prune empty price levels from top of the bid heap."""
        while self._bid_heap:
            best_neg_tick = self._bid_heap[0]
            tick = -best_neg_tick
            q = self._bids.get(tick)
            if q and len(q) > 0:
                break
            heapq.heappop(self._bid_heap)
            if tick in self._bids:
                del self._bids[tick]

    def _clean_best_ask(self):
        """Prune empty price levels from top of the ask heap."""
        while self._ask_heap:
            tick = self._ask_heap[0]
            q = self._asks.get(tick)
            if q and len(q) > 0:
                break
            heapq.heappop(self._ask_heap)
            if tick in self._asks:
                del self._asks[tick]

    def get_best_bid(self) -> Optional[Tuple[float, int]]:
        """
        Returns (best_bid_price, aggregate_quantity) or None if book is empty on buy side.
        """
        self._clean_best_bid()
        if not self._bid_heap:
            return None
        best_tick = -self._bid_heap[0]
        q = self._bids[best_tick]
        total_qty = sum(o.quantity for o in q)
        return (self._ticks_to_price(best_tick), total_qty)

    def get_best_ask(self) -> Optional[Tuple[float, int]]:
        """
        Returns (best_ask_price, aggregate_quantity) or None if book is empty on sell side.
        """
        self._clean_best_ask()
        if not self._ask_heap:
            return None
        best_tick = self._ask_heap[0]
        q = self._asks[best_tick]
        total_qty = sum(o.quantity for o in q)
        return (self._ticks_to_price(best_tick), total_qty)

    def get_spread(self) -> Optional[float]:
        """
        Returns the bid/ask spread (best_ask - best_bid) or None if one side is empty.
        """
        bb = self.get_best_bid()
        ba = self.get_best_ask()
        if bb is None or ba is None:
            return None
        return round(ba[0] - bb[0], 4)

    def get_depth(self, levels: int = 5) -> Tuple[List[PriceLevel], List[PriceLevel]]:
        """
        Returns top N bid and ask price levels with aggregate quantities.
        """
        self._clean_best_bid()
        self._clean_best_ask()

        bids_depth: List[PriceLevel] = []
        asks_depth: List[PriceLevel] = []

        # Extract sorted unique bids
        sorted_bids = sorted(self._bids.keys(), reverse=True)
        for tick in sorted_bids:
            q = self._bids.get(tick)
            if q and len(q) > 0:
                qty = sum(o.quantity for o in q)
                bids_depth.append(PriceLevel(
                    price=self._ticks_to_price(tick),
                    total_quantity=qty,
                    order_count=len(q)
                ))
                if len(bids_depth) >= levels:
                    break

        # Extract sorted unique asks
        sorted_asks = sorted(self._asks.keys())
        for tick in sorted_asks:
            q = self._asks.get(tick)
            if q and len(q) > 0:
                qty = sum(o.quantity for o in q)
                asks_depth.append(PriceLevel(
                    price=self._ticks_to_price(tick),
                    total_quantity=qty,
                    order_count=len(q)
                ))
                if len(asks_depth) >= levels:
                    break

        return (bids_depth, asks_depth)

    def get_recent_trades(self, limit: int = 20) -> List[Trade]:
        """Returns the most recent executed trades up to limit."""
        trades = list(self._recent_trades)
        return trades[-limit:] if limit > 0 else trades

    def cancel_order(self, order_id: int) -> bool:
        """
        Cancel a resting order by order ID.

        Returns:
            True if order was found and cancelled, False otherwise.
        """
        entry = self._orders_by_id.pop(order_id, None)
        if entry is None:
            return False

        ticks, side, target_order = entry
        target_dict = self._bids if side == Side.BUY else self._asks
        q = target_dict.get(ticks)
        if q is not None:
            try:
                q.remove(target_order)
                return True
            except ValueError:
                pass
        return False

    def add_resting_order(self, order: Order):
        """
        Insert an order directly into the book as a resting order without matching.
        """
        ticks = self._price_to_ticks(order.price)
        side = order.side

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

        self._orders_by_id[order.order_id] = (ticks, side, order)

    def process_order(self, order: Order) -> List[Trade]:
        """
        Execute Price-Time Priority matching for an incoming order.

        Rules:
            1. Buy order matches lowest available sell price when buy limit >= sell price.
            2. Sell order matches highest available buy price when sell limit <= buy price.
            3. Resting order determines the executed trade price.
            4. At same price level, earlier resting orders execute first (FIFO).
            5. Decrements matched quantities; removes fully filled orders.
            6. Adds any unexecuted residual quantity to the book as a resting order.
            7. Self-trade prevention skips matches if order IDs are identical.

        Returns:
            List of generated Trade executions.
        """
        t0 = time.perf_counter_ns()
        self.total_orders_processed += 1
        trades: List[Trade] = []

        if order.quantity <= 0:
            return trades

        order_ticks = self._price_to_ticks(order.price)
        remaining_qty = order.quantity
        now_ns = time.time_ns

        if order.side == Side.BUY:
            # Match against ASKS: lowest ask price first
            while remaining_qty > 0:
                self._clean_best_ask()
                if not self._ask_heap:
                    break

                best_ask_tick = self._ask_heap[0]
                # Price cross condition: Buy limit price must be >= Ask limit price
                if order_ticks < best_ask_tick:
                    break

                ask_queue = self._asks[best_ask_tick]
                while ask_queue and remaining_qty > 0:
                    resting_ask = ask_queue[0]

                    # Self-trade prevention check
                    if self.self_trade_prevention and resting_ask.order_id == order.order_id:
                        break

                    matched_qty = min(remaining_qty, resting_ask.quantity)
                    exec_price = self._ticks_to_price(best_ask_tick)  # Resting order sets price

                    self._trade_counter += 1
                    trade = Trade(
                        trade_id=self._trade_counter,
                        price=exec_price,
                        quantity=matched_qty,
                        buy_order_id=order.order_id,
                        sell_order_id=resting_ask.order_id,
                        timestamp_ns=now_ns(),
                    )
                    trades.append(trade)
                    self._recent_trades.append(trade)

                    self.total_trades_executed += 1
                    self.total_volume_executed += matched_qty
                    remaining_qty -= matched_qty

                    if resting_ask.quantity == matched_qty:
                        # Fully filled: remove resting order
                        ask_queue.popleft()
                        self._orders_by_id.pop(resting_ask.order_id, None)
                    else:
                        # Partial fill: update remaining quantity on resting order
                        resting_ask.quantity -= matched_qty
                        break

                if not ask_queue:
                    heapq.heappop(self._ask_heap)
                    del self._asks[best_ask_tick]

        else:
            # Sell order: match against BIDS: highest bid price first
            while remaining_qty > 0:
                self._clean_best_bid()
                if not self._bid_heap:
                    break

                best_bid_tick = -self._bid_heap[0]
                # Price cross condition: Sell limit price must be <= Bid limit price
                if order_ticks > best_bid_tick:
                    break

                bid_queue = self._bids[best_bid_tick]
                while bid_queue and remaining_qty > 0:
                    resting_bid = bid_queue[0]

                    # Self-trade prevention check
                    if self.self_trade_prevention and resting_bid.order_id == order.order_id:
                        break

                    matched_qty = min(remaining_qty, resting_bid.quantity)
                    exec_price = self._ticks_to_price(best_bid_tick)  # Resting order sets price

                    self._trade_counter += 1
                    trade = Trade(
                        trade_id=self._trade_counter,
                        price=exec_price,
                        quantity=matched_qty,
                        buy_order_id=resting_bid.order_id,
                        sell_order_id=order.order_id,
                        timestamp_ns=now_ns(),
                    )
                    trades.append(trade)
                    self._recent_trades.append(trade)

                    self.total_trades_executed += 1
                    self.total_volume_executed += matched_qty
                    remaining_qty -= matched_qty

                    if resting_bid.quantity == matched_qty:
                        # Fully filled: remove resting order
                        bid_queue.popleft()
                        self._orders_by_id.pop(resting_bid.order_id, None)
                    else:
                        # Partial fill: update remaining quantity on resting order
                        resting_bid.quantity -= matched_qty
                        break

                if not bid_queue:
                    heapq.heappop(self._bid_heap)
                    del self._bids[best_bid_tick]

        # Any unexecuted residual quantity rests in the book
        if remaining_qty > 0:
            residual_order = Order(
                order_id=order.order_id,
                price=order.price,
                quantity=remaining_qty,
                side=order.side,
                timestamp_ns=order.timestamp_ns,
            )
            self.add_resting_order(residual_order)

        t1 = time.perf_counter_ns()
        latency = t1 - t0
        self.last_match_latency_ns = latency
        self.total_match_latency_ns += latency

        return trades


# Unified export: use native Cython engine if compiled, otherwise Python fallback
if CYTHON_AVAILABLE and CythonLimitOrderBook is not None:
    LimitOrderBook = CythonLimitOrderBook
    IS_NATIVE_CYTHON = True
else:
    LimitOrderBook = PyLimitOrderBook
    IS_NATIVE_CYTHON = False
