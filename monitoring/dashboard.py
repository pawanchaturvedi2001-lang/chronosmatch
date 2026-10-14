"""
ChronosMatch Real-Time Terminal Dashboard (Week 2)
Curses-based live monitoring interface for Limit Order Book, trade tape, and latency metrics.

Features:
- Section A: System Status (Title, Mode, Engine & Simulator State, Counts, Throughput)
- Section B: Live Order Book (Best Bid/Ask, Spread, Top 5 L2 Market Depth)
             Columns: | Bid quantity | Bid price | Ask price | Ask quantity |
- Section C: Recent Executed Trades (Time, Trade ID, Price, Quantity, Buy ID, Sell ID)
- Section D: Performance & Latency Metrics (Engine Latency Mean/P95/P99, E2E Latency, Throughput)
- Safe terminal resizing, safe boundary rendering, and graceful shutdown.
"""

import sys
import time
import asyncio
from typing import Optional, List, Any

# Safe curses import across platforms
try:
    import curses
    HAVE_CURSES = True
except ImportError:
    curses = None
    HAVE_CURSES = False

from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON
from core.models import Trade, PriceLevel


def safe_addstr(stdscr, y: int, x: int, text: str, attr: int = 0):
    """
    Safely writes text to stdscr without raising curses.error on window boundary overflows.
    """
    try:
        max_y, max_x = stdscr.getmaxyx()
        if y < max_y and x < max_x:
            avail = max_x - x - 1
            if avail > 0:
                stdscr.addstr(y, x, text[:avail], attr)
    except curses.error:
        pass


class OrderBookDashboard:
    """
    Real-time curses dashboard displaying order book state, market depth,
    trade tape, and execution statistics.
    """

    def __init__(
        self,
        lob: LimitOrderBook,
        engine: Optional[Any] = None,
        refresh_hz: float = 10.0,
        auto_exit: bool = False,
    ):
        """
        Args:
            lob: LimitOrderBook instance to monitor.
            engine: Optional ChronosEngine instance for pipeline and latency statistics.
            refresh_hz: Refresh rate in Hz (default: 10.0 updates/sec).
            auto_exit: If True, exits immediately when pipeline finishes.
                       If False, keeps displaying final state until 'q' is pressed.
        """
        self.lob = lob
        self.engine = engine
        self.refresh_interval = 1.0 / max(1.0, refresh_hz)
        self.auto_exit = auto_exit
        self.is_running = False

        self._has_colors = False
        self._last_orders_count = 0
        self._last_calc_time = time.perf_counter()
        self._current_throughput = 0.0

    def _init_colors(self):
        """Initialize color pairs if terminal supports them."""
        if curses:
            try:
                if curses.has_colors():
                    curses.start_color()
                    curses.use_default_colors()
                    curses.init_pair(1, curses.COLOR_GREEN, -1)   # Bids / Success
                    curses.init_pair(2, curses.COLOR_RED, -1)     # Asks / Alerts
                    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Spread / Trades
                    curses.init_pair(4, curses.COLOR_CYAN, -1)    # Section Headers
                    curses.init_pair(5, curses.COLOR_MAGENTA, -1) # Title
                    self._has_colors = True
            except curses.error:
                self._has_colors = False

    def _draw_frame(self, stdscr):
        """Render a single frame of the dashboard."""
        max_y, max_x = stdscr.getmaxyx()

        # Handle small terminals gracefully
        if max_y < 24 or max_x < 80:
            stdscr.clear()
            msg = f"Terminal too small ({max_x}x{max_y}). Min required size: 80x24. Resize window."
            safe_addstr(stdscr, 0, 0, msg)
            stdscr.refresh()
            return

        stdscr.erase()

        # Color attributes
        color_green = curses.color_pair(1) if self._has_colors else 0
        color_red = curses.color_pair(2) if self._has_colors else 0
        color_yellow = curses.color_pair(3) if self._has_colors else 0
        color_cyan = curses.color_pair(4) if self._has_colors else 0
        color_title = curses.color_pair(5) if self._has_colors else 0
        bold = curses.A_BOLD if curses else 0
        underline = curses.A_UNDERLINE if curses else 0

        # Retrieve performance stats from engine if attached
        if self.engine is not None:
            stats = self.engine.get_performance_stats()
            sim_status = stats["simulator_status"]
            eng_status = stats["engine_status"]
            m_mean = stats["match_latency_mean_us"]
            m_p95 = stats["match_latency_p95_us"]
            m_p99 = stats["match_latency_p99_us"]
            e_mean = stats["e2e_latency_mean_us"]
            e_p95 = stats["e2e_latency_p95_us"]
            e_p99 = stats["e2e_latency_p99_us"]
            throughput = stats["throughput_ops"]
            orders_count = stats["orders_consumed"]
            trades_count = stats["trades_generated"]
        else:
            sim_status = "N/A"
            eng_status = "RUNNING"
            orders_count = self.lob.total_orders_processed
            trades_count = self.lob.total_trades_executed

            now = time.perf_counter()
            dt = now - self._last_calc_time
            if dt >= 0.5:
                delta = orders_count - self._last_orders_count
                self._current_throughput = delta / dt if dt > 0 else 0.0
                self._last_orders_count = orders_count
                self._last_calc_time = now
            throughput = self._current_throughput

            avg_lat_us = (self.lob.total_match_latency_ns / max(1, orders_count)) / 1000.0
            last_lat_us = self.lob.last_match_latency_ns / 1000.0
            m_mean = avg_lat_us
            m_p95 = last_lat_us
            m_p99 = last_lat_us
            e_mean = 0.0
            e_p95 = 0.0
            e_p99 = 0.0

        mode_str = "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON FALLBACK"

        # ======================================================================
        # SECTION A: SYSTEM STATUS
        # ======================================================================
        title = "=== ChronosMatch: Zero-Copy High-Frequency Trading Engine ==="
        safe_addstr(stdscr, 0, max(0, (max_x - len(title)) // 2), title, color_title | bold)

        status_line = (
            f"Engine: {eng_status} | Mode: {mode_str} | "
            f"Simulator: {sim_status} | Press 'q' to quit"
        )
        safe_addstr(stdscr, 1, max(0, (max_x - len(status_line)) // 2), status_line, color_cyan)

        # Border
        safe_addstr(stdscr, 2, 0, "=" * (max_x - 1))

        # ======================================================================
        # SECTION B: LIVE ORDER BOOK (Top 5 L2 Market Depth)
        # Required format: | Bid quantity | Bid price | Ask price | Ask quantity |
        # ======================================================================
        best_bid = self.lob.get_best_bid()
        best_ask = self.lob.get_best_ask()
        spread = self.lob.get_spread()

        bid_top_str = f"Best Bid: {best_bid[0]:.2f} (Qty: {best_bid[1]:,})" if best_bid else "Best Bid: NONE"
        ask_top_str = f"Best Ask: {best_ask[0]:.2f} (Qty: {best_ask[1]:,})" if best_ask else "Best Ask: NONE"
        spread_top_str = f"Spread: {spread:.2f}" if spread is not None else "Spread: N/A"

        row = 3
        safe_addstr(stdscr, row, 2, "LIVE ORDER BOOK (L2)", color_cyan | bold)
        safe_addstr(stdscr, row, 24, bid_top_str, color_green | bold)
        safe_addstr(stdscr, row, 48, spread_top_str, color_yellow | bold)
        safe_addstr(stdscr, row, 64, ask_top_str, color_red | bold)

        # Exact 4-column Table Header
        row = 4
        col_header = "| Bid quantity |  Bid price  |  Ask price  | Ask quantity |"
        start_x = 2
        safe_addstr(stdscr, row, start_x, col_header, underline | bold)

        # Depth rows (Top 5 levels)
        bids_depth, asks_depth = self.lob.get_depth(levels=5)
        for i in range(5):
            curr_row = 5 + i
            # Format Bid Side
            if i < len(bids_depth):
                b = bids_depth[i]
                bid_qty_str = f"{b.total_quantity:>12,}"
                bid_px_str = f"{b.price:>11.2f}"
            else:
                bid_qty_str = f"{'-':>12}"
                bid_px_str = f"{'-':>11}"

            # Format Ask Side
            if i < len(asks_depth):
                a = asks_depth[i]
                ask_px_str = f"{a.price:>11.2f}"
                ask_qty_str = f"{a.total_quantity:>12,}"
            else:
                ask_px_str = f"{'-':>11}"
                ask_qty_str = f"{'-':>12}"

            line = f"| {bid_qty_str} | {bid_px_str} | {ask_px_str} | {ask_qty_str} |"
            safe_addstr(stdscr, curr_row, start_x, line)

        # ======================================================================
        # SECTION C: RECENT EXECUTED TRADES
        # ======================================================================
        safe_addstr(stdscr, 10, 0, "-" * (max_x - 1))
        safe_addstr(stdscr, 11, 2, "RECENT EXECUTED TRADES", color_cyan | bold)

        trades_header = "| Time     | Trade ID   | Price      | Quantity | Buy Order  | Sell Order |"
        safe_addstr(stdscr, 12, 2, trades_header, underline)

        recent_trades = self.lob.get_recent_trades(limit=5)
        if recent_trades:
            for idx, t in enumerate(recent_trades):
                curr_row = 13 + idx
                ts_str = time.strftime("%H:%M:%S", time.localtime(t.timestamp_ns / 1e9))
                t_line = (
                    f"| {ts_str:<8} | #{t.trade_id:<9} | {t.price:<10.2f} | "
                    f"{t.quantity:<8,} | #{t.buy_order_id:<9} | #{t.sell_order_id:<9} |"
                )
                safe_addstr(stdscr, curr_row, 2, t_line, color_yellow)
        else:
            safe_addstr(stdscr, 13, 4, "(No trades executed yet)")

        # ======================================================================
        # SECTION D: PERFORMANCE & LATENCY METRICS
        # ======================================================================
        safe_addstr(stdscr, 18, 0, "-" * (max_x - 1))
        safe_addstr(stdscr, 19, 2, "PERFORMANCE & LATENCY METRICS", color_cyan | bold)

        # Row 20: Operational counters
        line_perf1 = (
            f"Orders Processed: {orders_count:,} | "
            f"Trades: {trades_count:,} | "
            f"Current Throughput: {throughput:,.1f} orders/sec"
        )
        safe_addstr(stdscr, 20, 2, line_perf1)

        # Row 21: Matching Engine micro-latency (Mean, P95, P99)
        line_perf2 = (
            f"Engine Latency:  Mean: {m_mean:6.2f} us | "
            f"P95: {m_p95:6.2f} us | "
            f"P99: {m_p99:6.2f} us (Hot-path C/Cython match)"
        )
        safe_addstr(stdscr, 21, 2, line_perf2, color_green if m_mean < 20.0 else color_yellow)

        # Row 22: Pipeline End-to-End latency (Simulator -> IPC -> Consumer -> Book)
        line_perf3 = (
            f"Pipeline E2E:    Mean: {e_mean:6.2f} us | "
            f"P95: {e_p95:6.2f} us | "
            f"P99: {e_p99:6.2f} us (Zero-loss IPC ring buffer)"
        )
        safe_addstr(stdscr, 22, 2, line_perf3, color_cyan)

        # Footer
        safe_addstr(stdscr, 23, 0, "=" * (max_x - 1))

        stdscr.refresh()

    def run_curses(self, stdscr):
        """Blocking curses loop for standalone terminal use."""
        curses.curs_set(0)
        stdscr.nodelay(True)
        self._init_colors()
        self.is_running = True

        while self.is_running:
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q'), 27):  # 'q', 'Q', or ESC
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
            print("[Warning] Curses not available. Running in headless mode.")
            return

        def _curses_runner(stdscr):
            curses.curs_set(0)
            stdscr.nodelay(True)
            self._init_colors()
            self.is_running = True

            while self.is_running:
                ch = stdscr.getch()
                if ch in (ord('q'), ord('Q'), 27):
                    self.is_running = False
                    if stop_event is not None:
                        stop_event.set()
                    break
                elif ch == curses.KEY_RESIZE:
                    stdscr.clear()

                if stop_event is not None and stop_event.is_set():
                    if self.auto_exit:
                        self.is_running = False
                        break

                self._draw_frame(stdscr)
                time.sleep(self.refresh_interval)

        try:
            await asyncio.to_thread(curses.wrapper, _curses_runner)
        except curses.error as e:
            if "Redirection is not supported" in str(e):
                # When run in headless/piped environments (e.g. CI or subprocess redirection),
                # wait until stop_event is set
                while not (stop_event is not None and stop_event.is_set()):
                    await asyncio.sleep(self.refresh_interval)
            else:
                raise


def launch_dashboard(
    lob: LimitOrderBook,
    engine: Optional[Any] = None,
    refresh_hz: float = 10.0,
):
    """Entry point to start the curses dashboard synchronously."""
    if not HAVE_CURSES:
        raise RuntimeError("Python curses module is required to run the terminal dashboard.")
    dash = OrderBookDashboard(lob, engine=engine, refresh_hz=refresh_hz, auto_exit=False)
    try:
        curses.wrapper(dash.run_curses)
    except curses.error as e:
        if "Redirection is not supported" in str(e):
            print("[Notice] Curses interactive UI requires a real console TTY. Redirection is not supported.")
        else:
            raise
