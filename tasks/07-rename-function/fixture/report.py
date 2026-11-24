from pricing import calc_total


def summary(carts):
    """Sum of calc_total over several carts (no tax)."""
    return round(sum(calc_total(c) for c in carts), 2)
