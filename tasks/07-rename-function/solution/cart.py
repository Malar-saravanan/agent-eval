from pricing import compute_total


def checkout(items):
    # uses compute_total with a flat 10% tax
    return compute_total(items, 10)
