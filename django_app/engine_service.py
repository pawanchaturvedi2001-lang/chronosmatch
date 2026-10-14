"""
ChronosMatch Backend Engine Service
Thread-safe singleton coordinator bridging Django with the native Cython
Limit Order Book, shared-memory RingBuffer, and Market Simulator.
"""

import time
import threading
import asyncio
from collections import deque
from typing import Dict, Any, Optional, List, Tuple

from ipc.structures import Order, Side, ORDER_SIZE, pack_order, unpack_order
from ipc.ring_buffer import RingBuffer
from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from core.models import Trade, PriceLevel
from simulator.market_simulator import run_simulator


class MarketEngineService:
    """
    Manages the lifecycle of the matching engine, live order book,
    manual order submissions, and background simulation workers.
    """

    _instance: Optional["MarketEngineService"] = None
    _init_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.RLock()
        self.lob = LimitOrderBook(tick_size=0.01)

        # Operational metrics
        self.orders_processed = 0
        self.trades_executed = 0
        self.total_volume = 0
        self.last_price: Optional[float] = None
        self._manual_order_counter = 900_000

        # Latency sliding window in microseconds
        self.match_latencies: deque = deque(maxlen=20000)
        self.e2e_latencies: deque = deque(maxlen=20000)

        # Throughput tracking
        self._last_calc_time = time.perf_counter()
        self._last_orders_count = 0
        self.current_throughput = 0.0

        # Simulator state and thread management
        self.simulator_running = False
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_stop_event = threading.Event()
        self._active_ring_buffer: Optional[RingBuffer] = None

    @classmethod
    def get_instance(cls) -> "MarketEngineService":
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def submit_manual_order(self, side_str: str, price: float, quantity: int) -> Dict[str, Any]:
        """
        Submits a validated simulated manual order into the matching engine.

        Args:
            side_str: "BUY" or "SELL".
            price: Order limit price (must be positive).
            quantity: Order size (must be positive integer).

        Returns:
            Dict containing order execution status and matched trades.
        """
        side_clean = str(side_str).strip().upper()
        if side_clean not in ("BUY", "SELL"):
            return {"success": False, "error": f"Invalid order side '{side_str}'. Must be BUY or SELL."}

        try:
            px = float(price)
            if px <= 0.0:
                return {"success": False, "error": "Price must be strictly positive."}
            px = round(px, 2)
        except (ValueError, TypeError):
            return {"success": False, "error": "Price must be a valid decimal number."}

        try:
            qty = int(quantity)
            if qty <= 0:
                return {"success": False, "error": "Quantity must be a positive integer."}
        except (ValueError, TypeError):
            return {"success": False, "error": "Quantity must be an integer."}

        with self._lock:
            self._manual_order_counter += 1
            order_id = self._manual_order_counter
            side_val = Side.BUY if side_clean == "BUY" else Side.SELL
            now_ns = time.time_ns()

            order = Order(
                order_id=order_id,
                price=px,
                quantity=qty,
                side=side_val,
                timestamp_ns=now_ns,
            )

            # Hot-path match execution
            t0 = time.perf_counter_ns()
            trades: List[Trade] = self.lob.process_order(order)
            t1 = time.perf_counter_ns()

            match_us = (t1 - t0) / 1000.0
            self.match_latencies.append(match_us)
            self.orders_processed += 1
            self.trades_executed += len(trades)

            filled_qty = sum(t.quantity for t in trades)
            if trades:
                self.last_price = trades[-1].price
                self.total_volume += filled_qty

            if filled_qty == qty:
                status = "FILLED"
            elif filled_qty > 0:
                status = "PARTIALLY_FILLED"
            else:
                status = "RESTING"

            return {
                "success": True,
                "order_id": order_id,
                "side": side_clean,
                "price": px,
                "quantity": qty,
                "status": status,
                "filled_quantity": filled_qty,
                "remaining_quantity": qty - filled_qty,
                "trades_count": len(trades),
                "trades": [t.to_dict() for t in trades],
            }

    def start_simulator(self, total_orders: int = 5000, target_rate: int = 25000) -> Tuple[bool, str]:
        """
        Launches the background market simulator and IPC consumer worker.
        """
        with self._lock:
            if self.simulator_running:
                return False, "Simulator is already active and generating market orders."

            self.simulator_running = True
            self._sim_stop_event.clear()

            def _worker():
                asyncio.run(self._run_simulation_pipeline(total_orders, target_rate))

            self._sim_thread = threading.Thread(target=_worker, name="ChronosSimWorker", daemon=True)
            self._sim_thread.start()
            return True, f"Simulator started: {total_orders:,} orders at target rate {target_rate:,} ops/s."

    async def _run_simulation_pipeline(self, total_orders: int, target_rate: int):
        """
        Asynchronous pipeline draining the shared-memory RingBuffer into the matching engine.
        """
        ring_buffer = RingBuffer(capacity=65536, slot_size=ORDER_SIZE)
        self._active_ring_buffer = ring_buffer
        batch_size = 500
        stop_consumer = asyncio.Event()

        async def _consumer():
            rb_read = ring_buffer.read
            process_order = self.lob.process_order
            unpack = unpack_order
            time_ns = time.time_ns

            while not stop_consumer.is_set():
                if self._sim_stop_event.is_set():
                    break

                batch_count = 0
                while batch_count < batch_size:
                    data = rb_read()
                    if data is None:
                        break
                    order = unpack(data)

                    # E2E pipeline latency
                    now_ns = time_ns()
                    if order.timestamp_ns > 0:
                        e2e_us = (now_ns - order.timestamp_ns) / 1000.0
                        if e2e_us >= 0:
                            self.e2e_latencies.append(e2e_us)

                    # Match order under engine lock
                    with self._lock:
                        t0 = time.perf_counter_ns()
                        trades = process_order(order)
                        match_us = (time.perf_counter_ns() - t0) / 1000.0
                        self.match_latencies.append(match_us)

                        self.orders_processed += 1
                        self.trades_executed += len(trades)
                        if trades:
                            self.last_price = trades[-1].price
                            self.total_volume += sum(t.quantity for t in trades)

                    batch_count += 1

                if batch_count == 0:
                    await asyncio.sleep(0.001)

            # Drain remaining items
            while True:
                data = rb_read()
                if data is None:
                    break
                order = unpack(data)
                with self._lock:
                    trades = process_order(order)
                    self.orders_processed += 1
                    self.trades_executed += len(trades)
                    if trades:
                        self.last_price = trades[-1].price
                        self.total_volume += sum(t.quantity for t in trades)

        consumer_task = asyncio.create_task(_consumer())

        try:
            rate_param = target_rate if target_rate > 0 else None
            await run_simulator(
                ring_buffer=ring_buffer,
                total_orders=total_orders,
                target_orders_per_sec=rate_param,
                batch_size=batch_size,
                backpressure_mode="wait",
            )
        except Exception as e:
            pass
        finally:
            stop_consumer.set()
            await consumer_task
            ring_buffer.close()
            with self._lock:
                self.simulator_running = False
                self._active_ring_buffer = None

    def stop_simulator(self) -> Tuple[bool, str]:
        """Stops an active background simulator."""
        self._sim_stop_event.set()
        if self._sim_thread and self._sim_thread.is_alive() and threading.current_thread() != self._sim_thread:
            self._sim_thread.join(timeout=3.0)
        with self._lock:
            self.simulator_running = False
        return True, "Stop signal transmitted to simulator worker."

    def reset_book(self) -> Tuple[bool, str]:
        """Resets the Limit Order Book and trade tape to a fresh state."""
        if self.simulator_running:
            self.stop_simulator()
        elif self._sim_thread and self._sim_thread.is_alive() and threading.current_thread() != self._sim_thread:
            self._sim_stop_event.set()
            self._sim_thread.join(timeout=3.0)

        with self._lock:
            self.lob = LimitOrderBook(tick_size=0.01)
            self.orders_processed = 0
            self.trades_executed = 0
            self.total_volume = 0
            self.last_price = None
            self.match_latencies.clear()
            self.e2e_latencies.clear()
            self._last_calc_time = time.perf_counter()
            self._last_orders_count = 0
            self.current_throughput = 0.0
            return True, "Limit Order Book and trade tape reset successfully."

    def get_market_data(self) -> Dict[str, Any]:
        """
        Generates a complete real-time market data snapshot for frontend consumption.
        """
        with self._lock:
            # Update rolling throughput
            now = time.perf_counter()
            dt = now - self._last_calc_time
            if dt >= 0.5:
                delta = self.orders_processed - self._last_orders_count
                self.current_throughput = delta / dt if dt > 0 else 0.0
                self._last_orders_count = self.orders_processed
                self._last_calc_time = now

            best_bid = self.lob.get_best_bid()
            best_ask = self.lob.get_best_ask()
            spread = self.lob.get_spread()

            # Level 2 Depth (top 10 levels)
            bids_depth, asks_depth = self.lob.get_depth(levels=10)

            # Recent Trades Tape (up to 20 trades)
            trades_raw = self.lob.get_recent_trades(limit=20)
            trades_list = [
                {
                    "trade_id": t.trade_id,
                    "price": t.price,
                    "quantity": t.quantity,
                    "buy_order_id": t.buy_order_id,
                    "sell_order_id": t.sell_order_id,
                    "timestamp_ns": t.timestamp_ns,
                }
                for t in trades_raw
            ]

            # Latency Percentiles calculation
            def _percentiles(samples: deque):
                if not samples:
                    return 0.0, 0.0, 0.0
                s = sorted(samples)
                n = len(s)
                mean_v = sum(s) / n
                p95_v = s[min(int(n * 0.95), n - 1)]
                p99_v = s[min(int(n * 0.99), n - 1)]
                return mean_v, p95_v, p99_v

            m_mean, m_p95, m_p99 = _percentiles(self.match_latencies)
            e_mean, e_p95, e_p99 = _percentiles(self.e2e_latencies)

            return {
                "engine_mode": "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON FALLBACK",
                "is_native_cython": IS_NATIVE_CYTHON,
                "engine_status": "RUNNING",
                "simulator_running": self.simulator_running,
                "last_price": self.last_price,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": spread,
                "depth": {
                    "bids": [{"price": b.price, "total_quantity": b.total_quantity, "order_count": b.order_count} for b in bids_depth],
                    "asks": [{"price": a.price, "total_quantity": a.total_quantity, "order_count": a.order_count} for a in asks_depth],
                },
                "recent_trades": trades_list,
                "metrics": {
                    "orders_processed": self.orders_processed,
                    "trades_executed": self.trades_executed,
                    "total_volume": self.total_volume,
                    "throughput_ops": self.current_throughput,
                    "latency": {
                        "match_mean_us": m_mean,
                        "match_p95_us": m_p95,
                        "match_p99_us": m_p99,
                        "e2e_mean_us": e_mean,
                        "e2e_p95_us": e_p95,
                        "e2e_p99_us": e_p99,
                    },
                },
            }


def get_engine_service() -> MarketEngineService:
    """Convenience accessor function."""
    return MarketEngineService.get_instance()
