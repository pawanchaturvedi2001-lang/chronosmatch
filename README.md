# ChronosMatch

Project structure for the ChronosMatch matching engine.

## Components

- `django_app/` — Django application
- `core/` — order book and matching engine implementations
- `ipc/` — inter-process communication buffers and shared structures
- `simulator/` — market simulator
- `monitoring/` — latency monitoring
- `persistence/` — trade persistence
- `tests/` — test suite
- `docs/` — project documentation

## Member 2: IPC and market simulation

- `ipc/` — order structures, memory-mapped storage, and ring buffer
- `simulator/` — asynchronous market-order generator
- `consumer/` — ring-buffer order consumer
- `benchmarks/week1_benchmark.py` — in-memory order-production benchmark
- `docs/week1.md` — Week 1 scope and run instructions

Run the test suite from the repository root with `python -m pytest tests`.
