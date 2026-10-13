"""
ChronosMatch Real-Time Terminal Dashboard (Week 2)
Curses-based live monitoring interface for Limit Order Book, trade tape, and latency metrics.

Features:
- Best Bid, Best Ask, Spread, and Level 2 Market Depth
- Live Trade Tape (recent executions)
- Performance metrics (throughput, orders processed, fill volume, latency in microseconds)
- Terminal resize handling and graceful shutdown
- Safe fallback for small terminals and non-TTY environments
"""

import sys
import time
import asyncio
from typing import Optional, List

# Import curses with safe handling
try:
    import curses
    HAVE_CURSES = True
except ImportError:
    curses = None
    HAVE_CURSES = False

from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from core.models import Trade, PriceLevel


class OrderBookDashboard:
    """
    Real-time curses dashboard displaying order book state, market depth,
    trade tape, and execution statistics.
    """

    def __init__(self, lob: LimitOrderBook, refresh_hz: float = 10.0):
        """
        Args:
            lob: LimitOrderBook instance to observe.
            refresh_hz: UI refresh frequency in Hz (defaults to 10 updates/sec).
        """
        self.lob = lob
        self.refresh_interval = 1.0 / max(1.0, refresh_hz)
        self.is_running = False
        self._last_orders_count = 0
        self._last_calc_time = time.perf_counter()
        self._current_throughput = 0.0

    def _init_colors(self):
        """Initialize color pairs if terminal supports them."""
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)   # Bids
            curses.init_pair(2, curses.COLOR_RED, -1)     # Asks
            curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Warnings / Spread
            curses.init_pair(4, curses.COLOR_CYAN, -1)    # Headers / Info
            curses.init_pair(5, curses.COLOR_MAGENTA, -1) # Title

    def _draw_frame(self, stdscr):
        """Render a single frame of the dashboard."""
        max_y, max_x = stdscr.getmaxyx()

        # Handle small terminals gracefully
        if max_y < 22 or max_x < 78:
            stdscr.clear()
            msg = f"Terminal too small ({max_x}x{max_y}). Min size: 80x24. Resize window."
            stdscr.addstr(0, 0, msg[:max_x - 1])
            stdscr.refresh()
            return

        stdscr.erase()

        # Update throughput calculation
        now = time.perf_counter()
        dt = now - self._last_calc_time
        if dt >= 0.5:
            delta_orders = self.lob.total_orders_processed - self._last_orders_count
            self._current_throughput = delta_orders / dt if dt > 0 else 0.0
            self._last_orders_count = self.lob.total_orders_processed
            self._last_calc_time = now

        mode_str = "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON FALLBACK"
        color_green = curses.color_pair(1) if curses.has_colors() else 0
        color_red = curses.color_pair(2) if curses.has_colors() else 0
        color_yellow = curses.color_pair(3) if curses.has_colors() else 0
        color_cyan = curses.color_pair(4) if curses.has_colors() else 0
        color_title = curses.color_pair(5) if curses.has_colors() else 0

        # Header banner
        title = "=== ChronosMatch: Zero-Copy High-Frequency Trading Engine ==="
        stdscr.addstr(0, max(0, (max_x - len(title)) // 2), title[:max_x - 1], color_title | curses.A_BOLD)
        status_line = f"Engine: RUNNING | Mode: {mode_str} | Press 'q' to exit"
        stdscr.addstr(1, max(0, (max_x - len(status_line)) // 2), status_line[:max_x - 1], color_cyan)
        stdscr.hline(2, 0, "=", max_x - 1)

        # Top of Book & Spread
        best_bid = self.lob.get_best_bid()
        best_ask = self.lob.get_best_ask()
        spread = self.lob.get_spread()

        bid_str = f"Best Bid: {best_bid[0]:.2f} (qty: {best_bid[1]:,})" if best_bid else "Best Bid: NONE"
        ask_str = f"Best Ask: {best_ask[0]:.2f} (qty: {best_ask[1]:,})" if best_ask else "Best Ask: NONE"
        spread_str = f"Spread: {spread:.2f}" if spread is not None else "Spread: N/A"

        row = 3
        stdscr.addstr(row, 2, bid_str[:max_x - 3], color_green | curses.A_BOLD)
        stdscr.addstr(row, 30, spread_str[:max_x - 31], color_yellow | curses.A_BOLD)
        stdscr.addstr(row, 50, ask_str[:max_x - 51], color_red | curses.A_BOLD)

        stdscr.hline(4, 0, "-", max_x - 1)

        # Level 2 Depth (Top 5 levels)
        stdscr.addstr(5, 2, "MARKET DEPTH (L2)", color_cyan | curses.A_BOLD)
        stdscr.addstr(6, 2, f"{'BID QTY':<10} {'BID PRICE':<12} | {'ASK PRICE':<12} {'ASK QTY':<10}", curses.A_UNDERLINE)

        bids_depth, asks_depth = self.lob.get_depth(levels=5)
        for i in range(5):
            curr_row = 7 + i
            bid_part = ""
            if i < len(bids_depth):
                b = bids_depth[i]
                bid_part = f"{b.total_quantity:<10,} {b.price:<12.2f}"
            else:
                bid_part = f"{'-':<10} {'-':<12}"

            ask_part = ""
            if i < len(asks_depth):
                a = asks_depth[i]
                ask_part = f"{a.price:<12.2f} {a.total_quantity:<10,}"
            else:
                ask_part = f"{'-':<12} {'-':<10}"

            line = f"{bid_part} | {ask_part}"
            stdscr.addstr(curr_row, 2, line[:max_x - 3])

        stdscr.hline(12, 0, "-", max_x - 1)

        # Recent Trades Tape
        stdscr.addstr(13, 2, "RECENT EXECUTED TRADES", color_cyan | curses.A_BOLD)
        stdscr.addstr(14, 2, f"{'TIME':<12} {'TRADE ID':<10} {'PRICE':<10} {'QTY':<8} {'BUY ID':<10} {'SELL ID':<10}", curses.A_UNDERLINE)

        trades = self.lob.get_recent_trades(limit=5)
        for i, t in enumerate(trades):
            curr_row = 15 + i
            ts_str = time.strftime("%H:%M:%S", time.localtime(t.timestamp_ns / 1e9))
            t_line = f"{ts_str:<12} {t.trade_id:<10} {t.price:<10.2f} {t.quantity:<8,} {t.buy_order_id:<10} {t.sell_order_id:<10}"
            stdscr.addstr(curr_row, 2, t_line[:max_x - 3], color_yellow)

        stdscr.hline(20, 0, "-", max_x - 1)

        # Performance & Latency Statistics
        avg_lat_us = 0.0
        if self.lob.total_orders_processed > 0:
            avg_lat_us = (self.lob.total_match_latency_ns / self.lob.total_orders_processed) / 1000.0

        last_lat_us = self.lob.last_match_latency_ns / 1000.0

        stdscr.addstr(21, 2, "PERFORMANCE METRICS", color_cyan | curses.A_BOLD)
        stat1 = f"Orders Processed: {self.lob.total_orders_processed:,} | Trades: {self.lob.total_trades_executed:,} | Filled Volume: {self.lob.total_volume_executed:,}"
        stat2 = f"Throughput: {self._current_throughput:,.1f} orders/sec | Latency (avg): {avg_lat_us:.2f} us | Latency (last): {last_lat_us:.2f} us"

        stdscr.addstr(22, 2, stat1[:max_x - 3])
        stdscr.addstr(23, 2, stat2[:max_x - 3], color_green if avg_lat_us < 50.0 else color_yellow)

        stdscr.refresh()

    def run_curses(self, stdscr):
        """Blocking curses loop (for standalone terminal use)."""
        curses.curs_set(0)
        stdscr.nodelay(True)
        self._init_colors()
        self.is_running = True

        while self.is_running:
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q'), 27):  # 'q' or ESC
                self.is_running = False
                break
            elif ch == curses.KEY_RESIZE:
                stdscr.clear()

            self._draw_frame(stdscr)
            time.sleep(self.refresh_interval)

    async def render_loop_async(self, stop_event: Optional[asyncio.Event] = None):
        """
        Asynchronous render loop that refreshes the dashboard without blocking asyncio.
        """
        if not HAVE_CURSES:
            print("[Warning] Curses not available. Running headless mode.")
            return

        def _curses_runner(stdscr):
            curses.curs_set(0)
            stdscr.nodelay(True)
            self._init_colors()
            self.is_running = True

            while self.is_running:
                if stop_event is not None and stop_event.is_set():
                    self.is_running = False
                    break

                ch = stdscr.getch()
                if ch in (ord('q'), ord('Q'), 27):
                    self.is_running = False
                    if stop_event is not None:
                        stop_event.set()
                    break
                elif ch == curses.KEY_RESIZE:
                    stdscr.clear()

                self._draw_frame(stdscr)
                time.sleep(self.refresh_interval)

        await asyncio.to_thread(curses.wrapper, _curses_runner)


def launch_dashboard(lob: LimitOrderBook, refresh_hz: float = 10.0):
    """Entry point to start the curses dashboard."""
    if not HAVE_CURSES:
        raise RuntimeError("Python curses module is required to run the terminal dashboard.")
    dash = OrderBookDashboard(lob, refresh_hz=refresh_hz)
    curses.wrapper(dash.run_curses)
