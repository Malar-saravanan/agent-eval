import subprocess
import sys
from pathlib import Path


def run(*args):
    return subprocess.run([sys.executable, "agg.py", *args], capture_output=True, text=True, timeout=20)


def test_sales_by_region():
    r = run("sales.csv", "region", "amount")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["east,175", "north,10", "west,100"]


def test_other_columns(tmp_path):
    f = tmp_path / "other.csv"
    f.write_text("id,team,score,note\n1,red,5,x\n2,blue,7,y\n3,red,10,z\n4,green,1,w\n5,blue,3,v\n")
    r = run(str(f), "team", "score")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["blue,10", "green,1", "red,15"]


def test_group_by_product():
    r = run("sales.csv", "product", "amount")
    assert r.stdout.splitlines() == ["gadget,113", "widget,172"]
