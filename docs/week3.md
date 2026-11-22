# Week 3: Cython Optimization and Performance Monitoring

## 1. Objective
The main objective of Week 3 was to improve the performance of the ChronosMatch order matching system using Cython and monitor execution latency.

## 2. Cython Matching Helper
- Implemented the `match_quantity` helper in the Cython matching engine.
- The helper calculates the minimum quantity between two orders.
- Added handling for zero and negative quantities.
- Used Cython to improve execution speed.

## 3. Testing
- Created unit tests for the Cython matching helper.
- Tested positive, zero, and negative quantity values.
- Executed the complete project test suite.

**Testing result:** 34 tests passed successfully.

## 4. Performance Benchmarking
Compared Python and Cython execution performance.

| Implementation | Performance |
|---|---:|
| Python | 2,177,009 calls/second |
| Cython | 7,553,988 calls/second |

**Cython speedup: 3.47x**

## 5. Latency Monitoring
Implemented and executed the latency monitoring script.

Results from the test run:

- Total operations: 5
- Average latency: 0.4835 ms
- Minimum latency: 0.4625 ms
- Maximum latency: 0.4947 ms

## 6. Commands Used

```powershell
python -m pytest -v
python -m pytest tests/test_cython_engine.py -v
python -m benchmarks.benchmark_optimization
python monitoring/latency.py
```

## 7. Learning Outcomes
- Learned how Cython improves Python execution performance.
- Understood benchmarking and performance comparison.
- Learned how to measure execution latency.
- Improved understanding of testing and optimization.

## 8. Conclusion
Week 3 focused on Cython optimization, unit testing, performance benchmarking, and latency monitoring. All 34 project tests passed, and the Cython benchmark achieved a 3.47x speedup compared with the Python implementation in the measured test.