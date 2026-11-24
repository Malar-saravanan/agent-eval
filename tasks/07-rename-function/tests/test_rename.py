from pathlib import Path

import cart
import invoice
import pricing
import report

OLD = "calc_" + "total"


def test_new_name_exists():
    assert pricing.compute_total([(2, 3)]) == 6.0
    assert not hasattr(pricing, OLD)


def test_callers_work():
    assert cart.checkout([(10, 2), (5, 1)]) == 27.5
    assert invoice.invoice_line([(10, 2), (5, 1)]) == "TOTAL 25.00"
    assert report.summary([[(1, 2)], [(3, 3)]]) == 11.0


def test_old_name_absent_everywhere():
    for p in Path(".").rglob("*.py"):
        if "_hidden_tests" in p.parts or "__pycache__" in p.parts:
            continue
        assert OLD not in p.read_text(), f"{p} still mentions the old name"
