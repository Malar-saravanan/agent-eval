import pricing


def invoice_line(items):
    return f"TOTAL {pricing.calc_total(items, 0):.2f}"
