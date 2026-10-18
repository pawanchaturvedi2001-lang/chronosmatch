# Week 1: IPC and Market Simulator

## Scope

Week 1 implements a fixed-size binary order representation, memory-mapped
storage, a FIFO ring buffer, a consumer that decodes queued orders, and an
asynchronous market simulator that writes generated orders to the ring buffer.

## Project files

- `ipc/structures.py` defines `Order`, `Side`, and binary order packing.
- `ipc/mmap_buffer.py` provides file-backed or anonymous mapped storage.
- `ipc/ring_buffer.py` provides fixed-capacity FIFO storage over the mapped bytes.
- `simulator/market_simulator.py` generates and writes serialized orders.
- `consumer/consumer.py` reads and decodes orders from the ring buffer.
- `tests/` contains serialization, buffer, consumer, and simulator tests.
- `benchmarks/week1_benchmark.py` measures in-memory order production throughput.

## Run the tests

From the repository root:

```powershell
python -m pytest tests
```

## Run the benchmark

From the repository root:

```powershell
python -m benchmarks.week1_benchmark --count 100000
```

The benchmark uses an anonymous in-memory ring buffer and reports the time and
throughput for producing the requested number of serialized orders. Results
depend on the machine and Python runtime; they are measurements, not a
performance guarantee. The benchmark does not measure matching-engine
throughput or file-backed persistence.
