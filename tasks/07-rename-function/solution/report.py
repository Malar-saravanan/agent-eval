from pricing import compute_total


def summary(carts):
    """Sum of compute_total over several carts (no tax)."""
    return round(sum(compute_total(c) for c in carts), 2)
