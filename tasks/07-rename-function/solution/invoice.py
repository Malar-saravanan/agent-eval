import pricing


def invoice_line(items):
    return f"TOTAL {pricing.compute_total(items, 0):.2f}"
