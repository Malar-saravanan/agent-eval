from pricing import calc_total


def checkout(items):
    # uses calc_total with a flat 10% tax
    return calc_total(items, 10)
