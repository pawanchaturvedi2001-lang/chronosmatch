"""
Unit tests for ChronosMatch Latency Monitoring & Statistical Reservoir (Week 2).

Verifies:
1. Recording nanosecond durations and conversion to microseconds.
2. Direct microsecond recording.
3. Accurate statistical calculations: Mean, P50, P90, P95, P99, Min, Max.
4. Robust handling of empty reservoirs (returns 0.0, no ZeroDivisionError).
5. Robust rejection of invalid inputs (None, NaN, Inf, negative values).
6. Bounded sliding-window memory (oldest items pruned beyond max_samples).
7. PipelineLatencyMonitor decoupling engine, IPC, and E2E latencies without metric mixing.
8. Reset functionality.
"""

import math
import unittest
from monitoring.latency import LatencyTracker, PipelineLatencyMonitor


class TestLatencyTracker(unittest.TestCase):
    """Test suite for sliding-window LatencyTracker."""

    def test_empty_tracker_returns_zero(self):
        """Verify empty tracker returns 0.0 for all statistics without exceptions."""
        tracker = LatencyTracker("test_empty")
        self.assertEqual(tracker.count(), 0)
        self.assertEqual(tracker.mean_us(), 0.0)
        self.assertEqual(tracker.p50_us(), 0.0)
        self.assertEqual(tracker.p90_us(), 0.0)
        self.assertEqual(tracker.p95_us(), 0.0)
        self.assertEqual(tracker.p99_us(), 0.0)
        self.assertEqual(tracker.min_us(), 0.0)
        self.assertEqual(tracker.max_us(), 0.0)

        stats = tracker.get_stats()
        self.assertEqual(stats["test_empty_mean_us"], 0.0)
        self.assertEqual(stats["test_empty_samples_window"], 0)

    def test_nanosecond_recording_conversion(self):
        """Verify record_ns converts nanoseconds to microseconds correctly."""
        tracker = LatencyTracker("test_ns")
        # Record 5,000 ns -> 5.0 us, 12,500 ns -> 12.5 us
        tracker.record_ns(5_000)
        tracker.record_ns(12_500)

        self.assertEqual(tracker.count(), 2)
        self.assertAlmostEqual(tracker.mean_us(), 8.75, places=2)
        self.assertAlmostEqual(tracker.min_us(), 5.0, places=2)
        self.assertAlmostEqual(tracker.max_us(), 12.5, places=2)

    def test_percentile_calculations_exact(self):
        """Verify percentile calculations for known distribution 1..100."""
        tracker = LatencyTracker("test_percentiles", max_samples=500)
        for i in range(1, 101):
            tracker.record_us(float(i))

        self.assertEqual(tracker.count(), 100)
        # Mean of 1..100 = 50.5
        self.assertAlmostEqual(tracker.mean_us(), 50.5, places=1)
        # P50 (median)
        self.assertEqual(tracker.p50_us(), 51.0)
        # P90
        self.assertEqual(tracker.p90_us(), 91.0)
        # P95
        self.assertEqual(tracker.p95_us(), 96.0)
        # P99
        self.assertEqual(tracker.p99_us(), 100.0)
        # Min and Max
        self.assertEqual(tracker.min_us(), 1.0)
        self.assertEqual(tracker.max_us(), 100.0)

    def test_rejection_of_invalid_inputs(self):
        """Verify None, negative values, NaN, and Inf are cleanly rejected."""
        tracker = LatencyTracker("test_invalid")
        tracker.record_ns(None)
        tracker.record_ns(-100)
        tracker.record_us(-5.0)
        tracker.record_us(float("nan"))
        tracker.record_us(float("inf"))
        tracker.record_us(float("-inf"))

        self.assertEqual(tracker.count(), 0)
        self.assertEqual(tracker.invalid_samples_count, 6)

        # Valid sample should still record normally
        tracker.record_ns(10_000)
        self.assertEqual(tracker.count(), 1)
        self.assertEqual(tracker.mean_us(), 10.0)

    def test_bounded_sliding_window_memory(self):
        """Verify reservoir stays strictly within max_samples to prevent memory leak."""
        capacity = 100
        tracker = LatencyTracker("test_bounded", max_samples=capacity)

        # Push 250 samples (1 to 250)
        for val in range(1, 251):
            tracker.record_us(float(val))

        self.assertEqual(tracker.count(), capacity)
        self.assertEqual(tracker.total_recorded_count, 250)
        # Oldest samples (1..150) should be evicted; window holds 151..250
        self.assertEqual(tracker.min_us(), 151.0)
        self.assertEqual(tracker.max_us(), 250.0)

    def test_reset(self):
        """Verify reset clears all samples and counters."""
        tracker = LatencyTracker("test_reset")
        tracker.record_us(10.0)
        tracker.record_us(20.0)
        self.assertEqual(tracker.count(), 2)

        tracker.reset()
        self.assertEqual(tracker.count(), 0)
        self.assertEqual(tracker.total_recorded_count, 0)
        self.assertEqual(tracker.mean_us(), 0.0)


class TestPipelineLatencyMonitor(unittest.TestCase):
    """Test suite verifying decoupled pipeline latency tracking."""

    def test_pipeline_monitor_separate_categories(self):
        """Verify engine, IPC, and E2E latencies are recorded and reported separately."""
        monitor = PipelineLatencyMonitor(max_samples=1000)

        # Engine match: 5 microseconds (5,000 ns)
        monitor.record_engine_latency_ns(5_000)
        # IPC transit: 15 microseconds (15,000 ns)
        monitor.record_ipc_latency_ns(15_000)
        # E2E pipeline: 25 microseconds (25,000 ns)
        monitor.record_e2e_latency_ns(25_000)

        snapshot = monitor.get_snapshot()

        # Engine metrics
        self.assertEqual(snapshot["engine_match_mean_us"], 5.0)
        self.assertEqual(snapshot["engine_match_samples_window"], 1)

        # IPC metrics
        self.assertEqual(snapshot["ipc_transit_mean_us"], 15.0)
        self.assertEqual(snapshot["ipc_transit_samples_window"], 1)

        # E2E metrics
        self.assertEqual(snapshot["pipeline_e2e_mean_us"], 25.0)
        self.assertEqual(snapshot["pipeline_e2e_samples_window"], 1)

        # Verify they are not mixed
        self.assertNotEqual(snapshot["engine_match_mean_us"], snapshot["pipeline_e2e_mean_us"])


if __name__ == "__main__":
    unittest.main()
