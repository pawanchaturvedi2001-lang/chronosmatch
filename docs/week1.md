# ChronosMatch — Week 1: Market Firehose & IPC Ingestion

## Overview

ChronosMatch is a low-latency, zero-copy high-frequency trading (HFT) matching engine built in Python and Cython.

During **Week 1**, the objective is to establish the ingest and transport pipeline:
> **"Market Firehose: Build the asyncio script that blasts 100,000 mock trade orders per second into the IPC bus."**

This document details the architecture, design rationale, and technical considerations of the **Market Simulator** and **Mock Order Generator** developed for Week 1.

---

## Architecture Flow

The end-to-end data pipeline moves orders from the simulation loop directly into shared memory without JSON serialization or heap-allocation overhead:

```
Market Simulator
      ↓
asyncio
      ↓
Order Generator
      ↓
struct.pack()
      ↓
Ring Buffer
      ↓
mmap IPC
```

### Flow Breakdown

1. **Market Simulator (`simulator/market_simulator.py`)**:
   Orchestrates execution, drives asynchronous event loop batching, monitors throughput metrics, and applies backpressure strategies.
2. **asyncio**:
   Provides cooperative multitasking, allowing the simulator to blast orders concurrently while yielding control to matching engine workers or monitoring services without thread context switching overhead.
3. **Order Generator (`simulator/order_generator.py`)**:
   Produces high-fidelity, deterministic synthetic BUY and SELL orders with realistic price spreads, quantities, and nanosecond timestamps.
4. **struct.pack() (`ipc/structures.py`)**:
   Encodes high-level Python `Order` objects into fixed-size 29-byte binary representations (`<QdIBQ`) using Python's native C-level `struct` module, avoiding serialization bottlenecks.
5. **Ring Buffer (`ipc/ring_buffer.py`)**:
   A Single-Producer Single-Consumer (SPSC) circular queue residing in memory-mapped shared memory (`mmap`). Monotonic 64-bit sequence counters coordinate safe lock-free writes and reads.
6. **mmap IPC (`ipc/mmap_buffer.py`)**:
   Operating system level shared memory mapped directly into virtual memory. Allows the matching engine process to consume orders with true zero-copy IPC semantics.

---

## Core Questions and Design Rationale

### 1. What is a Market Simulator?
A **market simulator** is a synthetic engine that replicates the behavior and order flow of financial exchanges. In production electronic trading, participant firms (market makers, institutional traders, retail brokers) transmit thousands of continuous order cancellations, amendments, and placements into an exchange order book. The simulator acts as this collective market by continually minting realistic limit orders to stress-test downstream matching logic.

### 2. Why asyncio?
Traditional multi-threaded approaches in Python are constrained by the **Global Interpreter Lock (GIL)**. Spawning thousands of operating system threads or synchronizing queues incurs severe thread scheduling, context switching, and lock contention penalties.

`asyncio` provides:
- **Single-Threaded Cooperative Concurrency**: Executes order creation on an event-driven loop without GIL lock thrashing.
- **Microsecond Scheduling**: Eliminates thread context switches; tasks yield voluntarily at controlled batch boundaries (`await asyncio.sleep(0)`).
- **Extensibility**: Readily integrates with asynchronous WebSockets, network sockets, or monitoring dashboards in later weeks.

### 3. What is a Market Firehose?
In financial engineering, a **market firehose** refers to an unthrottled or extremely high-volume stream of market events designed to saturate ingestion channels. Real-time market data feeds (such as NASDAQ ITCH or CME MDP 3.0) blast tens of millions of market messages during peak volatility bursts (market open, macroeconomic data releases). The ChronosMatch market firehose simulates this extreme ingestion volume to uncover bottlenecks before live trading.

### 4. Why Generate Mock Orders?
- **Zero Financial and Regulatory Risk**: Testing on live exchanges requires regulatory licensing, broker connections, exchange fees, and financial risk.
- **Repeatability and Determinism**: By specifying a fixed random seed (`seed=42`), test scenarios can be reproduced identically, which is critical for verifying matching engine correctness.
- **Configurable Edge Cases**: Allows synthetic testing of corner cases such as order book imbalances, whale orders, spread crosses, and ring-buffer saturation under stress.

### 5. Why is 100,000 Orders/sec the Benchmark Target?
- **Industry Standard for Mid-Tier Matching Engines**: Modern electronic exchanges process order bursts between 50,000 and 500,000 orders/sec. Targeting 100,000 orders/second (an average of one order every 10 microseconds) ensures our IPC transport can support institutional-grade trading volume.
- **Baseline Ingestion Budget**: In a zero-copy architecture, inter-process transport must consume only a small fraction of the overall latency budget. Demonstrating 100k+ orders/sec ensures the ingestion layer will not become the bottleneck when paired with the Cython Limit Order Book.

### 6. Why Actual Throughput Depends on Hardware and System Architecture?
Throughput is not an abstract mathematical property; it is constrained by concrete physical and architectural factors:
- **CPU Cache Hierarchy (L1/L2/L3)**: Each order is 29 bytes. A ring buffer of 131,072 slots occupies ~3.8 MB, comfortably residing within modern CPU L3 caches. If the buffer spills into main RAM (DDR4/DDR5), memory bus latency can reduce throughput.
- **OS Page Faults & Virtual Memory**: Memory-mapped files (`mmap`) rely on OS page tables (typically 4 KB or 2 MB huge pages). First-time writes trigger minor page faults as pages are committed to physical RAM.
- **Core Clock Speed & Single-Thread Instructions**: In pure Python, generating random floats and packing structs is CPU-bound on a single core. Newer CPUs with higher single-core boost frequencies achieve proportionally higher throughput.
- **Storage Subsystem (File-backed mmap)**: If the mmap buffer is backed by a physical file on an HDD or SATA SSD rather than NVMe or RAM, OS page dirty flushes (`msync`) can cause micro-stalls unless memory-only mappings or asynchronous writebacks are employed.

---

## Backpressure Strategies

The RingBuffer has a finite capacity (e.g., 65,536 or 131,072 slots). If the producer (simulator) outpaces the consumer (matching engine), the buffer will fill.

ChronosMatch implements two distinct backpressure modes:

| Mode | Behavior | Use Case | Guarantees |
| :--- | :--- | :--- | :--- |
| **`wait` (Default)** | When full, the simulator yields execution via `await asyncio.sleep(retry_backoff)` and retries writing until slots are freed by the consumer. | **Production & Correctness**: Used during normal trading runs and integration testing. | **Zero Data Loss**: Every generated order is guaranteed to be delivered into the IPC bus. |
| **`drop`** | When full, the simulator drops the order, increments `orders_dropped` and `failed_writes`, and immediately proceeds to the next order. | **Benchmarking & Stress Testing**: Used to evaluate raw producer capacity without stalling on consumer latency. | **Loss Monitored**: Loss is recorded and reported; never silent. |

---

## Running the Simulator

### Basic Run (100,000 orders, default rate 100k/s):
```bash
python simulator/market_simulator.py --orders 100000 --rate 100000
```

### Unthrottled Max Speed Run:
```bash
python simulator/market_simulator.py --orders 100000 --rate 0 --buffer-capacity 131072
```

### Benchmark Run (Measuring throughput & backpressure):
```bash
python benchmarks/simulator_benchmark.py --orders 100000
```
