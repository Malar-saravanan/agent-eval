import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, "greet.py", *args], capture_output=True, text=True, timeout=20)


def test_defaults():
    r = run()
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Hello, World!"]


def test_name_and_times():
    r = run("--name", "Ada", "--times", "2")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["Hello, Ada!", "Hello, Ada!"]


def test_name_only():
    assert run("--name", "Bob").stdout.splitlines() == ["Hello, Bob!"]


def test_times_only():
    assert run("--times", "3").stdout.splitlines() == ["Hello, World!"] * 3


def test_bad_times():
    assert run("--times", "abc").returncode != 0
