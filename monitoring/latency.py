"""
ChronosMatch Latency Monitoring & Performance Reservoir Sampling (Week 2)
Provides microsecond-resolution latency tracking and statistical percentile computation.

Key Requirements:
- Records timing using time.perf_counter_ns().
- Calculates Mean, P50, P90, P95, and P99 percentiles.
- Strictly separates Matching Engine latency, IPC RingBuffer latency, and End-to-End pipeline latency.
- Bounded reservoir window to avoid unbounded memory growth.
- Robust handling of empty samples, zeroes, and invalid/negative numbers.
- Explicit microsecond (_us) and nanosecond (_ns) unit conventions.
"""

import time
from collections import deque
from typing import Dict, Any, List, Optional, Tuple
import math


class LatencyTracker:
    """
    Sliding-window statistical latency reservoir.

    Stores recorded latency values up to a maximum window capacity.
    Values can be recorded directly in nanoseconds or measured via a context manager.
    Percentiles and summary statistics are reported in microseconds (us) by default.
    """

    def __init__(self, name: str = "latency", max_samples: int = 20_000):
        """
        Initialize the latency tracker.

        Args:
            name: Identifier for this latency category (e.g. 'engine', 'ipc', 'e2e').
            max_samples: Maximum sliding-window sample capacity (prevents memory leak).
        """
        self.name = name
        self.max_samples = max(100, max_samples)
        # Store samples as floats representing microseconds
        self._samples: deque[float] = deque(maxlen=self.max_samples)
        self.total_recorded_count = 0
        self.invalid_samples_count = 0

    def record_ns(self, latency_ns: int) -> None:
        """
        Record a latency duration measured in nanoseconds.
        Converts to microseconds and appends to the reservoir.
        """
        if latency_ns is None or not isinstance(latency_ns, (int, float)):
            self.invalid_samples_count += 1
            return

        if math.isnan(latency_ns) or math.isinf(latency_ns) or latency_ns < 0:
            self.invalid_samples_count += 1
            return

        us = latency_ns / 1000.0
        self._samples.append(us)
        self.total_recorded_count += 1

    def record_us(self, latency_us: float) -> None:
        """
        Record a latency duration measured directly in microseconds.
        """
        if latency_us is None or not isinstance(latency_us, (int, float)):
            self.invalid_samples_count += 1
            return

        if math.isnan(latency_us) or math.isinf(latency_us) or latency_us < 0:
            self.invalid_samples_count += 1
            return

        self._samples.append(float(latency_us))
        self.total_recorded_count += 1

    def count(self) -> int:
        """Returns the number of active samples currently in the sliding window."""
        return len(self._samples)

    def mean_us(self) -> float:
        """Mean latency in microseconds. Returns 0.0 if empty."""
        n = len(self._samples)
        if n == 0:
            return 0.0
        return sum(self._samples) / n

    def percentile_us(self, p: float) -> float:
        """
        Calculate the p-th percentile (0 <= p <= 100) in microseconds using nearest-rank.
        Returns 0.0 if empty.
        """
        n = len(self._samples)
        if n == 0:
            return 0.0

        if p <= 0.0:
            return min(self._samples)
        if p >= 100.0:
            return max(self._samples)

        s = sorted(self._samples)
        rank = min(int(n * (p / 100.0)), n - 1)
        return float(s[rank])

    def p50_us(self) -> float:
        """50th percentile (median) in microseconds."""
        return self.percentile_us(50.0)

    def p90_us(self) -> float:
        """90th percentile in microseconds."""
        return self.percentile_us(90.0)

    def p95_us(self) -> float:
        """95th percentile in microseconds."""
        return self.percentile_us(95.0)

    def p99_us(self) -> float:
        """99th percentile in microseconds."""
        return self.percentile_us(99.0)

    def max_us(self) -> float:
        """Maximum observed latency in current window."""
        return max(self._samples) if self._samples else 0.0

    def min_us(self) -> float:
        """Minimum observed latency in current window."""
        return min(self._samples) if self._samples else 0.0

    def get_stats(self) -> Dict[str, float]:
        """
        Returns a complete statistical summary dictionary for this latency metric.
        All latencies are reported in microseconds (us).
        """
        return {
            f"{self.name}_mean_us": round(self.mean_us(), 2),
            f"{self.name}_p50_us": round(self.p50_us(), 2),
            f"{self.name}_p90_us": round(self.p90_us(), 2),
            f"{self.name}_p95_us": round(self.p95_us(), 2),
            f"{self.name}_p99_us": round(self.p99_us(), 2),
            f"{self.name}_min_us": round(self.min_us(), 2),
            f"{self.name}_max_us": round(self.max_us(), 2),
            f"{self.name}_samples_window": len(self._samples),
            f"{self.name}_total_count": self.total_recorded_count,
        }

    def reset(self) -> None:
        """Clear all stored latency samples."""
        self._samples.clear()
        self.total_recorded_count = 0
        self.invalid_samples_count = 0


class PipelineLatencyMonitor:
    """
    Coordinates latency telemetry across the three decoupled pipeline stages:
    1. Engine Execution Latency (pure LOB matching time per order).
    2. IPC Transport Latency (time spent in RingBuffer transit).
    3. End-to-End Pipeline Latency (order creation timestamp to trade completion).
    """

    def __init__(self, max_samples: int = 20_000):
        self.engine_tracker = LatencyTracker(name="engine_match", max_samples=max_samples)
        self.ipc_tracker = LatencyTracker(name="ipc_transit", max_samples=max_samples)
        self.e2e_tracker = LatencyTracker(name="pipeline_e2e", max_samples=max_samples)

    def record_engine_latency_ns(self, latency_ns: int) -> None:
        """Record pure matching engine execution duration."""
        self.engine_tracker.record_ns(latency_ns)

    def record_ipc_latency_ns(self, latency_ns: int) -> None:
        """Record IPC RingBuffer queue transit duration."""
        self.ipc_tracker.record_ns(latency_ns)

    def record_e2e_latency_ns(self, latency_ns: int) -> None:
        """Record total end-to-end pipeline latency."""
        self.e2e_tracker.record_ns(latency_ns)

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Produce a comprehensive performance snapshot with clean separation of stages.
        """
        snapshot = {}
        snapshot.update(self.engine_tracker.get_stats())
        snapshot.update(self.ipc_tracker.get_stats())
        snapshot.update(self.e2e_tracker.get_stats())
        return snapshot

    def reset(self) -> None:
        """Reset all category trackers."""
        self.engine_tracker.reset()
        self.ipc_tracker.reset()
        self.e2e_tracker.reset()
