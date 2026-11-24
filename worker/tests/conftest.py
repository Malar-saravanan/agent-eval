"""Test bootstrap: env + sys.path are fixed BEFORE any worker module is imported (they read env at import time).

Everything is offline: no Azure, no real harness binaries, no docker. Tests run unprivileged (uid=None).
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

WORKER = Path(__file__).resolve().parent.parent
REPO = WORKER.parent
_SANDBOX = Path(tempfile.mkdtemp(prefix="worker-tests-"))

os.environ.setdefault("MODELS_FILE", str(REPO / "config" / "models.yaml"))
os.environ["TASKS_DIR"] = str(_SANDBOX / "tasks")
os.environ["RUNS_DIR"] = str(_SANDBOX / "runs")
os.environ["TASKS_SRC"] = str(_SANDBOX / "no-tasks-src")
os.environ["HERMES_TEMPLATE"] = str(_SANDBOX / "hermes-template")
os.environ["XDG_CACHE_HOME"] = str(_SANDBOX / "cache")
os.environ["MODEL1_DEPLOYMENT"] = "dep-mini"
os.environ["AZURE_OPENAI_ENDPOINT"] = "https://azure.invalid"
os.environ["AZURE_OPENAI_API_VERSION"] = "2024-01-01"
os.environ["AZURE_OPENAI_API_KEY"] = "test-key"
os.environ.pop("JUDGE_MODEL", None)
(_SANDBOX / "hermes-template").mkdir()

# The unit_tests grader runs `python -m pytest` with a scrubbed env (PATH only): make `python` resolve to this interpreter.
_bin = _SANDBOX / "bin"
_bin.mkdir()
_shim = _bin / "python"
_shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
_shim.chmod(_shim.stat().st_mode | stat.S_IEXEC)
os.environ["PATH"] = f"{_bin}{os.pathsep}{os.environ['PATH']}"

sys.path.insert(0, str(WORKER))

import pytest  # noqa: E402
import yaml  # noqa: E402

import harnesses  # noqa: E402
import meter  # noqa: E402
import trial  # noqa: E402


@pytest.fixture(autouse=True)
def clean_meter():
    stores = (meter.USAGE, meter.BUDGETS, meter.EXHAUSTED, meter.RESOLVED, meter.OVERRIDES, meter.TOKENS, meter.BASE)
    for s in stores:
        s.clear()
    yield
    for s in stores:
        s.clear()


class TaskEnv:
    def __init__(self, root: Path):
        self.tasks = root / "tasks"
        self.runs = root / "runs"
        self.tasks.mkdir()

    def write_task(self, task_id="t1", **over) -> Path:
        t = {"id": task_id, "title": "x", "category": "exact", "prompt": "Say 42.",
             "grader": {"type": "exact_match", "expected": "42"}, "limits": {"timeout_s": 30, "max_turns": 20}}
        t.update(over)
        d = self.tasks / task_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "task.yaml").write_text(yaml.safe_dump(t))
        return d


@pytest.fixture
def task_env(tmp_path, monkeypatch):
    env = TaskEnv(tmp_path)
    monkeypatch.setattr(trial, "TASKS_DIR", env.tasks)
    monkeypatch.setattr(trial, "RUNS_DIR", env.runs)
    monkeypatch.setattr(os, "chown", lambda *a, **k: None)       # trial.run_trial chowns to a per-trial uid (needs root)
    monkeypatch.setattr(harnesses, "VERSIONS", {"fake": "9.9.9"})
    harnesses.READY.set()
    return env


def record_gateway_call(trial_id, prompt=10, completion=5):
    """What a real harness does implicitly: hit the metered gateway."""
    import time
    meter._record(trial_id, {"prompt_tokens": prompt, "completion_tokens": completion}, time.time())
