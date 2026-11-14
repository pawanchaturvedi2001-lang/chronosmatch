# ChronosMatch — Local Development & Windows Setup Guide

This guide provides complete, step-by-step instructions for running the **ChronosMatch Zero-Copy High-Frequency Trading Engine** and **Institutional Web Trading Terminal** on Windows 11.

---

## 1. System Prerequisites

1. **Windows 11 (64-bit)**
2. **Python 3.10 to 3.14 (64-bit)**
3. **Microsoft C++ Build Tools** (Visual Studio 2022 Build Tools with Desktop development with C++)
4. **PowerShell 7+** or **Windows PowerShell 5.1**

---

## 2. Quick Start (Automated PowerShell Launcher)

You can run the complete pre-flight check, virtual environment detection, Cython build verification, Django migration, port conflict check, and local server startup with one command:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_local.ps1
```

Or on standard Command Prompt / Terminal:
```cmd
python run_web.py
```

---

## 3. Manual Step-by-Step Installation

### Step A: Navigate to Project Directory
```powershell
cd C:\Users\e8353\Desktop\CHROMASMATCH\chronosmatch
```

### Step B: Create and Activate Virtual Environment (Optional)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step C: Install Python Dependencies
```powershell
python -m pip install -r requirements.txt
```

### Step D: Compile Native Cython Matching Engine
Compile the performance-critical Cython Limit Order Book (`.pyx`) into a native C extension (`.pyd`):
```powershell
python setup.py build_ext --inplace
```

### Step E: Verify Cython Native Extension Loading
```powershell
python -c "from core.order_book import IS_NATIVE_CYTHON; print('Cython loaded:', IS_NATIVE_CYTHON)"
```
*Expected output:* `Cython loaded: True`

### Step F: Run Database Migrations
```powershell
python manage.py migrate
```

---

## 4. Run the Automated Test Suite

Execute all 75 unit, integration, and regression tests across the Cython engine, shared-memory RingBuffer, Market Simulator, terminal dashboard, whale-sweep detection, and Django REST APIs:

```powershell
python -m pytest tests/ -v
```

*Expected result:* **75 passed in ~2.3s**

---

## 5. Launch the Local Web Trading Terminal

Start the Django development server:
```powershell
python manage.py runserver 127.0.0.1:8000
```
*(Or launch with `python run_web.py`)*

### Access the Web Terminal
Open your web browser to:
- 🌐 **Web Trading Terminal:** **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**
- 🩺 **Health Check API:** **[http://127.0.0.1:8000/api/health/](http://127.0.0.1:8000/api/health/)**
- 📊 **Consolidated Market Feed API:** **[http://127.0.0.1:8000/api/market-data/](http://127.0.0.1:8000/api/market-data/)**
- 🐋 **Whale Sweep Alerts API:** **[http://127.0.0.1:8000/api/sweeps/](http://127.0.0.1:8000/api/sweeps/)**

---

## 6. Standalone Terminal Curses Dashboard (Track B)

To run the real-time Curses terminal dashboard in a separate console window:
```powershell
python run_dashboard.py
```

Optional arguments:
```powershell
python run_dashboard.py --orders 50000 --rate 25000
```

---

## 7. Formal Benchmark Suites (Phase 5)

Run the empirical benchmark suites to verify real-world throughput and microsecond latency:

```powershell
# 1. Matching Engine Benchmark (10k, 100k, 1M orders)
python benchmarks/benchmark_engine.py --sizes 10000 100000 1000000

# 2. Multi-Process Shared-Memory IPC Benchmark
python -u benchmarks/benchmark_ipc.py

# 3. End-to-End Ingestion & Execution Pipeline Benchmark
python -u benchmarks/benchmark_pipeline.py --sizes 10000 100000
```

---

## 8. REST API Endpoints Reference

All endpoints return valid JSON and standard HTTP status codes:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health/` | Server health, Cython engine mode, simulator status, uptime |
| `GET` | `/api/market/` | Market overview: last price, best bid/ask, spread, session stats |
| `GET` | `/api/orderbook/` | Level 2 Order Book depth levels (`bids` and `asks` arrays) |
| `GET` | `/api/trades/` | Recent executed trades tape |
| `GET` | `/api/metrics/` | Throughput (ops/sec) and latency percentiles (Mean, P95, P99 in µs) |
| `GET` | `/api/sweeps/` | Whale sweep detection events, total count, and historical tape |
| `GET` | `/api/market-data/` | Consolidated real-time snapshot feed for fast frontend polling |
| `POST` | `/api/orders/` | Submit simulated manual order (`{"side": "BUY", "price": 100.5, "quantity": 50}`) |
| `POST` | `/api/simulator/start/` | Start market simulator firehose (`{"orders": 5000, "rate": 25000}`) |
| `POST` | `/api/simulator/stop/` | Gracefully stop the active background market simulator |
| `POST` | `/api/simulator/reset/` | Reset Order Book, latency buffers, and trade execution tape |

---

## 9. Troubleshooting & FAQ

- **PowerShell Script Execution Policy:**
  If PowerShell blocks script execution, invoke with execution policy bypass:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\start_local.ps1
  ```
- **Port 8000 in Use:**
  Specify a custom port:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\start_local.ps1 -Port 8080
  ```
- **Cython Native Extension Recompilation:**
  To force a clean rebuild:
  ```powershell
  python setup.py build_ext --inplace
  ```
- **Clean Safe Shutdown:**
  Press `Ctrl+C` in the running PowerShell terminal to safely terminate the Django development server and release shared-memory buffer mappings.
