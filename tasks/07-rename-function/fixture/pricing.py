def calc_total(items, tax_percent=0):
    """Total of (price, qty) pairs with tax_percent applied. calc_total([(2, 3)]) == 6.0"""
    subtotal = sum(price * qty for price, qty in items)
    return round(subtotal * (100 + tax_percent) / 100, 2)
