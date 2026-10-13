# ChronosMatch — Week 2: Cython Matching Engine & Real-Time Latency Dashboard

## 1. Executive Summary

During **Week 2** of the **ChronosMatch: Zero-Copy High-Frequency Trading Engine** project, development expanded from the Week 1 market ingestion firehose into the core matching and monitoring infrastructure:
- **Track A (Low-Latency Engineering)**: Implemented a Limit Order Book (LOB) with deterministic Price-Time Priority matching in both pure-Python (portable fallback) and Cython (`core/cython_engine/order_book.pyx`) with static C typing, `nogil` isolation, and reproducible build configuration (`setup.py`).
- **Track B (Market Logic and UI)**: Built a curses-based real-time terminal dashboard (`monitoring/dashboard.py`) showing top-of-book prices/quantities, Level 2 depth, spread, live trade executions, orders/sec throughput, and average/tail latency in microseconds.
- **End-to-End Pipeline**: Unified the simulator, IPC ring buffer, consumer worker, matching engine, and dashboard in `core/engine.py`.

---

## 2. Architecture & Data Flow

```text
Market Simulator (Producer)
          ↓ (binary Order struct: <QdIBQ, 29 bytes)
   IPC Ring Buffer (Shared Memory mmap)
          ↓ (zero-loss consumer worker)
Cython / Python Limit Order Book (LOB)
     ├── Price-Time Priority Matching Engine
     ├── Generated Trades & Level 2 Book Depth
     ↓
Real-Time Terminal Dashboard (curses) / Latency Monitor
```

### Component Breakdown
1. **`core/models.py`**:
   - `Trade`: Execution entity containing `trade_id`, `price`, `quantity`, `buy_order_id`, `sell_order_id`, and `timestamp_ns`.
   - `PriceLevel`: Aggregated depth entity containing `price`, `total_quantity`, and `order_count`.
2. **`core/order_book.py` / `core/cython_engine/order_book.pyx`**:
   - Limit Order Book maintaining separate priority queues for bids and asks.
   - Price levels are converted to integer ticks (`round(price / tick_size)`) to eliminate floating-point precision drift and ensure strict deterministic sorting.
   - Time priority is enforced at each price level via FIFO `deque` structures ($O(1)$ append and popleft).
   - `_orders_by_id` dictionary enables $O(1)$ order lookup and cancellation.
3. **`core/engine.py`**:
   - End-to-end pipeline coordinator. Launches concurrent producer (simulator), ring-buffer consumer, matching engine, and optional curses dashboard.
4. **`monitoring/dashboard.py`**:
   - Real-time curses dashboard with throttled non-blocking refresh (10 Hz), terminal resize protection, and graceful shutdown on 'q'.

---

## 3. Price-Time Priority Rules

Matching strictly complies with electronic exchange standards:
1. **Price Priority**:
   - Incoming BUY matches the lowest available SELL price if `buy_price >= ask_price`.
   - Incoming SELL matches the highest available BUY price if `sell_price <= bid_price`.
2. **Execution Price Determination**:
   - The executed trade price is determined by the **resting order's limit price** (the passive liquidity provider sets the price).
3. **Time Priority (FIFO)**:
   - For multiple orders resting at the identical price level, orders that arrived earlier execute first.
4. **Partial Fills & Residual Placement**:
   - If incoming quantity < resting quantity: resting order quantity is decremented; trade is recorded; incoming order completes.
   - If incoming quantity > resting quantity: resting order is removed; trade is recorded; remainder matches the next eligible order or rests on the book.
5. **Self-Trade Prevention (STP)**:
   - Orders matching against the same order ID are skipped to prevent circular wash trading.

---

## 4. Cython Compilation & Portability

### Build Configuration (`setup.py`)
The Cython extension is configured in `setup.py`:
```bash
python setup.py build_ext --inplace
```

### Technical Details & Tooling
- **Cython Version**: Cython 3.3.0
- **Python Version**: Python 3.14.3 (AMD64)
- **Compiler Directives**:
  - `language_level=3`
  - `boundscheck=False`
  - `wraparound=False`
  - `cdivision=True`
- **Compiler Optimization Flags**:
  - Windows (MSVC): `/O2 /fp:fast`
  - POSIX (GCC/Clang): `-O3 -march=native -ffast-math`

### Windows Compiler Tooling & Fallback
On 64-bit Windows running Python 3.14:
- The default MSVC compiler required for native `.pyd` compilation is **Microsoft C++ Build Tools 14.0+** (`cl.exe`).
- When MSVC is not installed or detected, `core/order_book.py` automatically falls back to `PyLimitOrderBook` with transparent status reporting:
  - `IS_NATIVE_CYTHON = False`
  - A banner alerts the user: `Mode: PURE PYTHON FALLBACK`
- When MSVC Build Tools are installed (`winget install Microsoft.VisualStudio.2022.BuildTools` with C++ workload), `python setup.py build_ext --inplace` generates the native `.pyd` module, switching `IS_NATIVE_CYTHON` to `True`.

### GIL (Global Interpreter Lock) Evaluation
- **Misconception**: Cython does *not* magically eliminate the Python GIL simply by compiling code.
- **Where `nogil` is genuinely used**: Pure C-level mathematical operations (integer tick conversions `c_price_to_ticks`, `c_ticks_to_price`, and minimum quantity comparisons `c_min_qty`) are executed in `nogil` blocks.
- **Where the GIL is required**: Instantiating Python `Trade` and `Order` objects, appending to Python lists, and interacting with Python heaps/deques requires the GIL. In Week 3, full C-struct pre-allocated arrays will permit extending `nogil` across the entire matching inner loop.

---

## 5. Terminal Dashboard Usage

### Windows Setup
On Windows, native curses is provided by `windows-curses`:
```bash
pip install windows-curses
```

### Running the End-to-End Engine with Live Dashboard
```bash
python -m core.engine --orders 100000 --rate 20000 --dashboard
```

### Running Headless (Max Throughput Benchmark)
```bash
python -m core.engine --orders 100000 --rate 0
```

### Dashboard Keyboard Controls
- `q` or `Q` or `ESC`: Graceful shutdown.
- Terminal resize: Automatically re-renders to fit new geometry.

---

## 6. Verification and Test Results

The test suite contains **26 automated unit and integration tests** across Week 1 and Week 2:

### Test Execution Command
```bash
python -m unittest discover tests -v
```

### Test Results Summary
```text
Ran 26 tests in 0.046s
OK
```

#### Detailed Breakdown of Week 2 Scenarios (`tests/test_order_book.py`)
| Test Name | Scenario Tested | Outcome |
| :--- | :--- | :--- |
| `test_buy_order_matching_sell_order` | Single BUY matching resting SELL | **PASS** |
| `test_sell_order_matching_buy_order` | Single SELL matching resting BUY | **PASS** |
| `test_no_match_when_prices_do_not_cross` | Bid < Ask, non-crossing spread | **PASS** |
| `test_best_price_priority` | Matches lowest ask / highest bid first | **PASS** |
| `test_time_priority_at_same_price` | FIFO execution for identical prices | **PASS** |
| `test_partial_execution_of_larger_order` | Remaining resting quantity updated | **PASS** |
| `test_one_incoming_order_matching_multiple_resting_orders` | Multi-order fill at single level | **PASS** |
| `test_multiple_price_levels_consumed` | Multi-level order book sweep | **PASS** |
| `test_correct_residual_quantity_after_partial_fills` | Residual added to resting book | **PASS** |
| `test_removal_of_completely_filled_orders` | Clean removal from active queues | **PASS** |
| `test_correct_best_bid_best_ask_and_spread` | Top-of-book and L2 depth calculations | **PASS** |
| `test_trade_records_integrity` | Order IDs, prices, quantities, timestamps | **PASS** |
| `test_empty_order_book_behavior` | Graceful handling on empty book | **PASS** |
| `test_invalid_order_handling` | Zero/negative quantity handling | **PASS** |
| `test_integration_with_simulator_and_order_format` | Full integration with Week 1 simulator | **PASS** |

---

## 7. Performance & Latency Benchmarks

### Benchmark Command
```bash
python benchmarks/matching_engine_benchmark.py --orders 50000
```

### Measured Benchmark Output
```text
=================================================================
      CHRONOSMATCH MATCHING ENGINE BENCHMARK REPORT
=================================================================
Engine Implementation:  PURE PYTHON FALLBACK
GIL Context:            Standard CPython GIL
-----------------------------------------------------------------
  PHASE 1: ENGINE-ONLY MATCHING (Zero IPC Overhead)
-----------------------------------------------------------------
Orders Submitted:       50,000
Trades Executed:        38,911
Total Volume Matched:   992,706
Elapsed Time:           0.2208 sec
Engine Throughput:      226,462.4 orders/sec

Latency Distribution (per-order match latency):
  Average (Mean):           4.14 us
  P50 (Median):             2.70 us
  P90:                      7.10 us
  P95:                      9.00 us
  P99:                     15.40 us
  Max Latency:           2214.60 us

-----------------------------------------------------------------
  PHASE 2: END-TO-END PIPELINE (Simulator -> RingBuffer -> LOB)
-----------------------------------------------------------------
Orders Written (IPC):   50,000
Orders Consumed & Exec: 50,000
Trades Executed:        38,911
Producer Elapsed:       0.4922 sec
Consumer Elapsed:       0.4894 sec
Producer Ingest Rate:   101,586.6 orders/sec
Consumer Match Rate:    102,163.1 orders/sec
Dropped Orders:         0
Backpressure Retries:   0
=================================================================
```

### Target Evaluation
- **Throughput**: Engine throughput achieved **226,462 orders/sec** (surpassing the 100,000 target).
- **Latency**: Mean matching latency achieved **4.14 microseconds** (P95: 9.00 µs, P99: 15.40 µs), well within the sub-50 microsecond latency goal.

---

## 8. Known Limitations & Mid-Project Review Roadmap

1. **Python Heap Overhead in Pure-Python Fallback**: While achieving >220k orders/sec, pure-Python execution is still bounded by GIL scheduling under multi-core threading.
2. **C-Level Pre-Allocated Depth**: In Week 3, pre-allocating contiguous memory pools for resting orders in Cython will eliminate dynamic heap allocation entirely.
3. **Mid-Project Review Goal**: 1,000,000 order end-to-end stress test across separate processes, background trade persistence (SQLite/ClickHouse), and whale-order detection.
