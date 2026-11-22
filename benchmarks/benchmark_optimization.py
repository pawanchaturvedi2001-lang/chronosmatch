import timeit

from core.cython_engine.matching_engine import match_quantity


def _python_match_quantity(buy_quantity, sell_quantity):
    if buy_quantity <= 0 or sell_quantity <= 0:
        return 0
    return min(buy_quantity, sell_quantity)


def benchmark_optimization(number=1_000_000, repeat=5):
    """Compare the Cython quantity helper with its Python equivalent."""
    cases = (
        ("Python", _python_match_quantity),
        ("Cython", match_quantity),
    )
    timings = {}

    for name, function in cases:
        timer = timeit.Timer(lambda: function(7, 5))
        elapsed = min(timer.repeat(repeat=repeat, number=number))
        timings[name] = elapsed
        print(
            f"{name}: {number / elapsed:,.0f} calls/second "
            f"(best of {repeat}: {elapsed:.4f}s)"
        )

    print(f"Cython speedup: {timings['Python'] / timings['Cython']:.2f}x")


if __name__ == "__main__":
    benchmark_optimization()
