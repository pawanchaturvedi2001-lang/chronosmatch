def match_quantity(buy_quantity: int, sell_quantity: int) -> int:
    """Return the matchable quantity, or zero for nonpositive inputs."""
    if buy_quantity <= 0 or sell_quantity <= 0:
        return 0
    return min(buy_quantity, sell_quantity)
