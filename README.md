# ChronosMatch: Zero-Copy High-Frequency Trading Engine & Web Terminal

ChronosMatch is a low-latency electronic trading engine featuring a zero-copy shared-memory Inter-Process Communication (IPC) bus, a native Cython Limit Order Book (LOB) with strict Price-Time Priority matching, a real-time `curses` terminal dashboard, and an interactive **Django Web Trading Terminal**.

---

## 1. Architecture & System Flow

```text
       Browser Web Terminal (Django + HTML/CSS/JS)
         ├── Real-Time Telemetry & L2 Depth Polling (/api/market-data/)
         ├── Manual Simulated Order Submission (/api/orders/)
         └── Background Simulator Lifecycle Controls (/api/simulator/)
                              ↕
            Django Backend Service (engine_service.py)
                              ↕
Market Simulator (Producer)          Manual Order Entry
        ↓                                    ↓
Binary Order Struct (<QdIBQ, 29 bytes)       │
        ↓                                    │
Shared-Memory RingBuffer (mmap IPC)          │
        ↓ (zero-loss consumer worker)        │
        └───────────────────┬────────────────┘
                            ↓
     Native Cython / Python Limit Order Book (LOB)
        ├── Deterministic Price-Time Priority Matching
        ├── Microsecond Latency Sampling (Mean, P95, P99)
        └── Executed Trade History & L2 Book Depth
                            ↓
   Terminal Curses Dashboard & Web Telemetry Stream
```

---

## 2. Key Features

### Track A — Low-Latency Matching Engine
- **Native Cython Acceleration**: Statically typed C structures (`uint64_t`, `uint32_t`, `int64_t`, `double`) compiled via Microsoft Visual C++ Build Tools into `core/cython_engine/order_book.cp314-win_amd64.pyd`.
- **Accurate GIL Isolation**: Uses pure C `nogil` functions (`c_price_to_ticks`, `c_ticks_to_price`, `c_min_qty`) for price scaling and min-comparison math.
- **Strict Price-Time Priority**: Best price matching (passive resting order sets price), FIFO execution at each level, residual quantity resting, and circular wash trading prevention (Self-Trade Prevention).
- **Zero-Copy IPC**: Shared-memory mmap RingBuffer with atomic pointer synchronization and zero data loss.

### Track B — Interactive Web Trading Terminal
- **Professional Dark Theme**: Inspired by institutional trading interfaces (TradingView / Bloomberg terminal aesthetics).
- **Level 2 Market Depth**: Top 10 bid and ask price levels with real-time proportional volume depth visualizers.
- **Simulated Order Entry Panel**: Manual BUY and SELL submission with limit price and quantity validation. Shows order IDs, fill status, and execution results.
- **Simulator Firehose Controls**: Start, stop, and reset controls to blast up to 100,000 mock orders/sec into the IPC bus.
- **Telemetry Charts**: Real-time streaming charts for market price and order throughput.
- **Latency Distribution**: Microsecond-resolution matching engine vs pipeline end-to-end latency metrics (Mean, P95, P99).

### Track C — Terminal Curses Dashboard
- Standalone terminal dashboard supporting VT100 / Windows terminal emulation with resize protection.

---

## 3. Project Structure

```text
chronosmatch/
├── core/                       # Core engine and models
│   ├── cython_engine/          # Native Cython .pyx, .c, and compiled .pyd
│   ├── models.py               # Trade and PriceLevel dataclasses
│   ├── order_book.py           # Pure-Python LOB and native Cython loader
│   ├── engine.py               # Asynchronous end-to-end pipeline coordinator
│   └── run_dashboard.py        # Dedicated curses runner
├── django_app/                 # Django Web Trading Terminal
│   ├── static/css/terminal.css # Dark trading terminal styling
│   ├── static/js/terminal.js   # Live polling, charts, and API integration
│   ├── templates/django_app/   # HTML5 templates
│   ├── engine_service.py       # Thread-safe backend singleton coordinator
│   ├── views.py                # REST API and terminal page views
│   ├── urls.py                 # Endpoint routing
│   └── settings.py             # Django project configuration
├── ipc/                        # Shared-memory IPC
│   ├── structures.py           # Binary 29-byte Order struct serialization
│   ├── mmap_buffer.py          # Memory-mapped memory buffer
│   └── ring_buffer.py          # RingBuffer with atomic head/tail
├── simulator/                  # Market firehose simulator
│   ├── order_generator.py      # Deterministic random order generator
│   └── market_simulator.py     # Asynchronous producer coroutine
├── monitoring/                 # Latency and book monitoring
│   └── dashboard.py            # Curses terminal dashboard
├── tests/                      # Automated test suite (40 tests)
│   ├── test_market_simulator.py
│   ├── test_order_book.py
│   ├── test_dashboard.py
│   └── test_django_web.py
├── benchmarks/                 # Latency and throughput benchmarks
│   ├── matching_engine_benchmark.py
│   └── simulator_benchmark.py
├── manage.py                   # Django CLI management entry point
├── run_dashboard.py            # Standalone curses entry point
├── setup.py                    # Cython compilation build script
└── requirements.txt            # Project dependencies
```

---

## 4. Prerequisites & Windows Setup

### 1. Requirements
- Python 3.10+ (tested on Python 3.14 AMD64)
- Microsoft Visual C++ Build Tools 14.0+ (required for Cython native compilation)

### 2. Virtual Environment Setup
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

---

## 5. Cython Build Instructions

Compile the native Cython matching engine extension:
```powershell
python setup.py build_ext --inplace
```
To verify Cython acceleration is active:
```powershell
python -c "from core.order_book import LimitOrderBook, IS_NATIVE_CYTHON; print('Native Cython Active:', IS_NATIVE_CYTHON)"
```

---

## 6. How to Run

### Option 1: Start the Web Trading Terminal
1. Apply database migrations:
   ```powershell
   python manage.py migrate
   ```
2. Start the development server:
   ```powershell
   python manage.py runserver
   ```
3. Open your browser and navigate to:
   ```text
   http://127.0.0.1:8000/
   ```

### Option 2: Run the Terminal Curses Dashboard
Launch the standalone curses terminal interface:
```powershell
python run_dashboard.py --orders 50000 --rate 25000
```
Or via the module:
```powershell
python -m core.run_dashboard --orders 100000 --rate 50000
```

### Option 3: Run Maximum-Throughput Headless Pipeline
```powershell
python -m core.engine --orders 100000 --rate 0
```

---

## 7. Running Tests & Benchmarks

### Execute Full Test Suite (40 Tests)
```powershell
python -m unittest discover tests -v
```

### Run Matching Engine Benchmarks
```powershell
python benchmarks/matching_engine_benchmark.py --orders 100000
```

### Verified Benchmark Baseline
- **Pure Cython Engine Throughput**: **469,555.0 orders/sec**
- **Average Match Latency**: **1.97 µs** (P95: **3.90 µs**, P99: **6.20 µs**)
- **IPC Pipeline Match Rate**: **179,962.3 orders/sec**
- **Data Loss / Dropped Orders**: **0**

---

## 8. REST API Reference

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/api/health/` | `GET` | System health check and engine mode. |
| `/api/market-data/` | `GET` | Snapshot of Level 2 depth, best bid/ask, recent trades, throughput, and latencies. |
| `/api/orders/` | `POST` | Submit simulated manual BUY/SELL order (`{"side": "BUY", "price": 100.5, "quantity": 50}`). |
| `/api/simulator/start/` | `POST` | Start background simulator (`{"orders": 5000, "rate": 25000}`). |
| `/api/simulator/stop/` | `POST` | Stop active background simulator. |
| `/api/simulator/reset/` | `POST` | Reset Order Book and trade tape to clean state. |
