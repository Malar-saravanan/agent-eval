"""Regression tests for the two failures that corrupted a first experiment run:
leaked harness daemons (memory exhaustion -> OOM kills) and runtime connection loss being scored as agent failure."""
import os
import subprocess
import sys
import time

import pytest

import harnesses
import trial

linux_only = pytest.mark.skipif(not os.path.isdir("/proc"), reason="reap() scans /proc (Linux)")


def _alive(p):
    return p.poll() is None


@linux_only
def test_reap_kills_processes_carrying_the_marker():
    env = {**os.environ, "OPENAI_API_KEY": "t_reaptest-1"}
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], env=env)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        time.sleep(0.3)
        harnesses.reap("t_reaptest-1")          # no uid: environment-marker mode (used by warm-up)
        p.wait(timeout=5)
        assert not _alive(p)
        assert _alive(other), "reap must not touch unrelated processes"
    finally:
        other.kill()
        p.kill()


@linux_only
def test_reap_never_kills_the_caller():
    harnesses.reap(str(os.getpid()))            # marker appears nowhere in our own environ; must be a no-op
    assert True


def test_lost_connection_messages_are_recognised():
    for msg in ("Gateway disconnected; turn outcome is unknown.", "read ECONNRESET", "Connection refused", "socket hang up"):
        assert trial.LOST_RE.search(msg), msg
    for msg in ("budget_exhausted: steps", "Refusing to overwrite lru.py", "tests failed"):
        assert not trial.LOST_RE.search(msg), msg


def test_only_reading_a_skill_counts_as_skill_use():
    assert harnesses._kind("skill_view") == "skill"
    assert harnesses._kind("skills_list") == "skill"
    assert harnesses._kind("skill") == "skill"            # opencode
    assert harnesses._kind("skill_manage") == "tool"      # edits a skill: not consulting it
    assert harnesses._kind("memory") == "memory"
    assert harnesses._kind("write_file") == "tool"


def test_hermes_trace_shows_memory_injected_into_the_session(tmp_path, monkeypatch):
    template, home, work = tmp_path / "tpl", tmp_path / "home", tmp_path / "work"
    for d in (template, home / "memories", work):
        d.mkdir(parents=True)
    (home / "memories" / "MEMORY.md").write_text("API port is 8081.")
    monkeypatch.setattr(harnesses, "TEMPLATE", template)
    monkeypatch.setattr(harnesses, "_run", lambda cmd, ctx, env: ([], False, 0, ""))
    ctx = harnesses.Ctx("t_mem", "do it", work, home, "gpt-4.1-mini", 5, 30)
    ev = harnesses.HARNESSES["hermes"].run(ctx).events
    call, res = ev[0], ev[1]
    assert call["name"] == "memory_context" and call["kind"] == "memory"
    assert "8081" in res["output"] and res["type"] == "tool_result"


def test_hermes_with_empty_memory_adds_no_memory_event(tmp_path, monkeypatch):
    template, home, work = tmp_path / "tpl", tmp_path / "home", tmp_path / "work"
    for d in (template, home / "memories", work):
        d.mkdir(parents=True)
    monkeypatch.setattr(harnesses, "TEMPLATE", template)
    monkeypatch.setattr(harnesses, "_run", lambda cmd, ctx, env: ([], False, 0, ""))
    assert harnesses.HARNESSES["hermes"].run(harnesses.Ctx("t_e", "x", work, home, "m", 5, 30)).events == []


@linux_only
def test_run_returns_promptly_and_kills_a_daemon_that_keeps_stdout_open(tmp_path):
    """Review finding: with pipes, `sh -c 'sleep 30 & echo hi'` blocked communicate() for 30s; a surviving daemon could
    also outlive the trial. Output now goes to files and leftovers are reaped."""
    ctx = harnesses.Ctx("t_dm1", "", tmp_path, tmp_path, "m", 5, 60)
    t0 = time.time()
    lines, timed_out, code, _ = harnesses._run(["sh", "-c", "sleep 31 & echo hi"], ctx, {"OPENAI_API_KEY": "t_dm1"})
    assert time.time() - t0 < 5 and lines == ["hi"] and not timed_out and code == 0
    time.sleep(0.3)
    left = [p for p in os.listdir("/proc") if p.isdigit() and b"sleep\x0031" in open(f"/proc/{p}/cmdline", "rb").read()]
    assert left == [], "daemon survived the reap"


@linux_only
def test_timeout_kills_the_whole_process_group_and_returns(tmp_path):
    ctx = harnesses.Ctx("t_dm2", "", tmp_path, tmp_path, "m", 5, 1)
    t0 = time.time()
    lines, timed_out, code, _ = harnesses._run(["sh", "-c", "sleep 32 & sleep 33"], ctx, {"OPENAI_API_KEY": "t_dm2"})
    assert timed_out and code == -1 and time.time() - t0 < 6
