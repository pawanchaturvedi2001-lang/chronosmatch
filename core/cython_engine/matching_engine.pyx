

# Cython-based matching quantity helper

cpdef int match_quantity(int buy_quantity, int sell_quantity):
    """Return the quantity that can be matched."""
    if buy_quantity <= 0 or sell_quantity <= 0:
        return 0

    if buy_quantity < sell_quantity:
        return buy_quantity

    return sell_quantity
