
import time
from statistics import mean


class LatencyMonitor:
    def __init__(self):
        self.latencies = []

    def start(self):
        return time.perf_counter_ns()

    def stop(self, start_time):
        end_time = time.perf_counter_ns()
        latency = (end_time - start_time) / 1000
        self.latencies.append(latency)
        return latency

    def record(self, operation):
        start_time = self.start()
        operation()
        return self.stop(start_time)

    def get_statistics(self):
        if not self.latencies:
            return {
                "count": 0,
                "average": 0,
                "minimum": 0,
                "maximum": 0
            }

        return {
            "count": len(self.latencies),
            "average": mean(self.latencies),
            "minimum": min(self.latencies),
            "maximum": max(self.latencies)
        }

    def display_report(self):
        stats = self.get_statistics()

        print("\n===== LATENCY REPORT =====")
        print(f"Total Operations : {stats['count']}")
        print(f"Average Latency  : {stats['average']:.2f} µs")
        print(f"Minimum Latency  : {stats['minimum']:.2f} µs")
        print(f"Maximum Latency  : {stats['maximum']:.2f} µs")
        print("==========================")


# Testing code - keep this at the bottom
if __name__ == "__main__":

    monitor = LatencyMonitor()

    monitor.record(lambda: sum(range(1000)))
    monitor.record(lambda: sum(range(5000)))
    monitor.record(lambda: sum(range(10000)))

    monitor.display_report()
