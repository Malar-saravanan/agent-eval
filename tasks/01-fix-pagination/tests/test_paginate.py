from paginate import paginate, total_pages


def test_first_page():
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]


def test_middle_page():
    assert paginate(list(range(10)), 2, 3) == [3, 4, 5]


def test_last_partial_page():
    assert paginate(list(range(10)), 4, 3) == [9]


def test_past_end():
    assert paginate(list(range(10)), 5, 3) == []


def test_exact_fit():
    assert paginate(list(range(6)), 2, 3) == [3, 4, 5]


def test_empty():
    assert paginate([], 1, 5) == []


def test_total_pages():
    assert total_pages(10, 3) == 4
