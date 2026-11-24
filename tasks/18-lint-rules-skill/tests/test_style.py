import ast
import re
from pathlib import Path

SRC = Path("app.py").read_text()
TREE = ast.parse(SRC)


def test_module_constants_prefixed():
    names = [t.id for node in TREE.body if isinstance(node, ast.Assign) for t in node.targets
             if isinstance(t, ast.Name)]
    assert names, "expected module-level constants"
    for n in names:
        assert re.fullmatch(r"CFG_[A-Z0-9_]+", n), n


def test_constant_values_kept():
    import app
    assert app.CFG_TIMEOUT == 30
    assert app.CFG_RETRIES == 3


def test_no_single_letter_names():
    for node in ast.walk(TREE):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assert len(node.id) > 2, node.id
        if isinstance(node, ast.arg):
            assert len(node.arg) > 2, node.arg


def test_end_comments():
    lines = SRC.splitlines()
    funcs = [n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)]
    assert {f.name for f in funcs} >= {"scale", "total"}
    for f in funcs:
        nxt = lines[f.end_lineno] if f.end_lineno < len(lines) else ""
        assert nxt.strip() == f"# end {f.name}", f.name
        assert len(nxt) - len(nxt.lstrip()) == f.body[0].col_offset, f.name


def test_behaviour_unchanged():
    import app
    assert app.scale(2, 3) == 6
    assert app.total([1, 2, 3]) == 6
    assert app.total([]) == 0
