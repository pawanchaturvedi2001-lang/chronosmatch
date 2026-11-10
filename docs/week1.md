
# ChronosMatch — Week 1: IPC and Market Simulator

## Overview

Week 1 implements the order ingestion and transport pipeline. It includes a fixed-size binary order format, memory-mapped storage, a FIFO ring buffer, a consumer that reads queued orders, and an asynchronous market simulator.

## Architecture

The data flow is:

1. The market simulator generates synthetic orders.
2. Orders are represented using the `Order` structure.
3. `pack_order` serializes each order into a fixed-size binary record.
4. The ring buffer stores records in mapped memory.
5. The consumer reads records and decodes them.

## Project files

- `ipc/structures.py` defines `Order`, `Side`, and binary order packing.
- `ipc/mmap_buffer.py` provides file-backed or anonymous mapped storage.
- `ipc/ring_buffer.py` provides fixed-capacity FIFO storage.
- `simulator/market_simulator.py` generates and writes serialized orders.
- `simulator/order_generator.py` generates synthetic orders.
- `consumer/consumer.py` reads and decodes orders.
- `tests/` contains serialization, buffer, consumer, and simulator tests.
- `benchmarks/week1_benchmark.py` measures order production throughput.
- `benchmarks/simulator_benchmark.py` measures simulator throughput.

## Design notes

### Why asyncio?

`asyncio` provides cooperative concurrency for the simulator. It allows the program to yield control between batches without creating a separate operating-system thread for every task.

### Why mock orders?

Synthetic orders make testing repeatable and avoid the financial and operational risks of connecting to a live exchange. They can also help test buffer capacity and producer-consumer behavior.

### Backpressure

The ring buffer has a finite capacity. If the producer writes faster than the consumer reads, the buffer can become full. The simulator must handle this condition according to its configured behavior, such as waiting or recording failed writes.

Actual throughput depends on hardware, Python runtime, buffer configuration, and workload. Benchmark results are measurements, not performance guarantees.

## Run the tests

From the repository root:

```powershell
python -m pytest tests
```

## Run the Week 1 benchmark

```powershell
python -m benchmarks.week1_benchmark --count 100000
```

## Run the simulator benchmark

```powershell
python -m benchmarks.simulator_benchmark --orders 100000
```

Use the command-line options supported by the current benchmark implementation.

## Binary Order Format

Orders are serialized into a fixed-size 29-byte binary record using the format `<QdIBQ`:

- `Q`: 8-byte unsigned order ID.
- `d`: 8-byte floating-point price.
- `I`: 4-byte unsigned quantity.
- `B`: 1-byte side value (`BUY` or `SELL`).
- `Q`: 8-byte unsigned timestamp.

The fields are stored in little-endian byte order. Use `pack_order` and `unpack_order` from `ipc/structures.py` to serialize and deserialize orders consistently.
