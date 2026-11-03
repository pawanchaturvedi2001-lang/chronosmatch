# ChronosMatch — Local Development & Setup Guide

This guide provides complete, step-by-step instructions for running the **ChronosMatch Zero-Copy High-Frequency Trading Engine** and **Institutional Web Trading Terminal** on Windows PowerShell / Command Prompt.

---

## 1. System Prerequisites

1. **Python 3.10, 3.11, 3.12, 3.13, or 3.14 (64-bit)**
2. **Microsoft C++ Build Tools** (Visual Studio 2022 or Build Tools with the *Desktop development with C++* workload)
3. **PowerShell** or **Command Prompt**

---

## 2. Quick Start (Automated Script)

You can launch the complete pre-flight check, Cython verification, and local web server with one PowerShell command:

```powershell
.\start_local.ps1
```

Or on standard Command Prompt:
```cmd
python run_web.py
```

---

## 3. Manual Step-by-Step Installation

### Step A: Clone & Navigate to Repository

```powershell
cd C:\Users\e8353\Desktop\CHROMASMATCH\chronosmatch
```

### Step B: Install Python Dependencies

```powershell
python -m pip install -r requirements.txt
```

### Step C: Build the Native Cython Matching Engine

Compile the performance-critical Cython Limit Order Book (`.pyx`) into a native C++ extension (`.pyd`):

```powershell
python setup.py build_ext --inplace
```

### Step D: Verify Cython Native Extension Loading

```powershell
python -c "from core.cython_engine import order_book; print('Cython native engine successfully loaded!')"
```

*Expected output:* `Cython native engine successfully loaded!`

---

## 4. Run the Test Suite

Execute all 44 unit and integration tests across the Cython engine, shared-memory RingBuffer, Market Simulator, terminal dashboard, and Django REST APIs:

```powershell
python -m pytest tests/ -v
```

*Expected result:* **44 passed in ~0.60s**

---

## 5. Launch the Local Web Trading Terminal

Start the Django development server:

```powershell
python manage.py runserver 127.0.0.1:8000
```
*(Or run `python run_web.py`)*

### Access the Web Terminal

Open your browser to:
- 🌐 **Web Trading Terminal:** **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

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

## 7. REST API Endpoints Reference

All endpoints return valid JSON and standard HTTP status codes:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health/` | Server health, Cython engine mode, simulator status, uptime |
| `GET` | `/api/market/` | Market overview: last price, best bid/ask, spread, session stats |
| `GET` | `/api/orderbook/` | Level 2 Order Book depth levels (`bids` and `asks` arrays) |
| `GET` | `/api/trades/` | Recent executed trades tape |
| `GET` | `/api/metrics/` | Throughput (ops/sec) and latency percentiles (Mean, P95, P99 in µs) |
| `GET` | `/api/market-data/` | Consolidated real-time snapshot feed for fast frontend polling |
| `POST` | `/api/orders/` | Submit simulated manual order (`{"side": "BUY", "price": 100.5, "quantity": 50}`) |
| `POST` | `/api/simulator/start/` | Start market simulator firehose (`{"orders": 5000, "rate": 25000}`) |
| `POST` | `/api/simulator/stop/` | Gracefully stop the active background market simulator |
| `POST` | `/api/simulator/reset/` | Reset Order Book, latency buffers, and trade execution tape |

---

## 8. Troubleshooting

- **DLL load failed / Access Denied:**
  Ensure you are running your PowerShell or terminal in standard user mode in the repository directory, or recompile the native extension:
  ```powershell
  python setup.py build_ext --inplace
  ```
- **Port 8000 Already in Use:**
  Run on a different port:
  ```powershell
  python manage.py runserver 127.0.0.1:8080
  ```
- **PowerShell Execution Policy Warning:**
  If you see script execution warnings, run PowerShell with execution policy bypass:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\start_local.ps1
  ```
