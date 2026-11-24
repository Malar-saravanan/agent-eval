import pytest

from roman import int_to_roman


@pytest.mark.parametrize("n,expected", [
    (1, "I"), (3, "III"), (4, "IV"), (9, "IX"), (14, "XIV"), (40, "XL"), (58, "LVIII"),
    (90, "XC"), (400, "CD"), (444, "CDXLIV"), (1994, "MCMXCIV"), (2024, "MMXXIV"), (3999, "MMMCMXCIX"),
])
def test_values(n, expected):
    assert int_to_roman(n) == expected


@pytest.mark.parametrize("n", [0, -5, 4000])
def test_out_of_range(n):
    with pytest.raises(ValueError):
        int_to_roman(n)
