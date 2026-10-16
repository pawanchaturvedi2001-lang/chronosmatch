
import time
from core.matching_engine import MatchingEngine


def benchmark_matching(number_of_orders=100_000):
    engine = MatchingEngine()

    start = time.perf_counter()

    for order_id in range(1, number_of_orders + 1):
        side = "SELL" if order_id % 2 == 1 else "BUY"

        engine.process_order({
            "order_id": order_id,
            "side": side,
            "price": 100,
            "quantity": 1,
        })

    elapsed = time.perf_counter() - start

    print("\n--- ChronosMatch Benchmark ---")
    print("Orders submitted:", number_of_orders)
    print(f"Time taken: {elapsed:.4f} seconds")
    print(
        f"Throughput: {number_of_orders / elapsed:.2f} orders/second"
    )
    print("Trades created:", len(engine.trades))
    print("Buy orders remaining:", len(engine.buy_orders))
    print("Sell orders remaining:", len(engine.sell_orders))


if __name__ == "__main__":
    benchmark_matching()
