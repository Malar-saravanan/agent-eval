import ast
from pathlib import Path

import helpers

NAMES = [n.name for n in ast.parse(Path("helpers.py").read_text()).body if isinstance(n, ast.FunctionDef)]


def test_all_functions_use_util_prefix():
    assert NAMES
    assert all(n.startswith("util_") for n in NAMES), NAMES


def test_some_util_function_reverses():
    ok = False
    for n in NAMES:
        try:
            f = getattr(helpers, n)
            ok = ok or (f("abc") == "cba" and f("") == "" and f("Hello World") == "dlroW olleH")
        except Exception:
            pass
    assert ok
