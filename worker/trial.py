"""Runs ONE trial in isolation: fresh workdir + fresh harness home, grade, return trace + metrics.

Invariant: a failure of the platform (harness crash, OOM-kill, lost connection, gateway/upstream errors, grader
breakage) is NEVER recorded as an agent failure. It becomes status infra_error / grader_error and is excluded from stats.
"""
import asyncio
import hashlib
import os
import re
import shutil
import threading
import time
from pathlib import Path

import yaml

import graders
import harnesses
import meter
from harnesses import HARNESSES, Ctx

TASKS_DIR = Path(os.environ.get("TASKS_DIR", "/srv/tasks"))      # root-only copy: hidden tests + solutions live here
TASKS_SRC = Path(os.environ.get("TASKS_SRC", "/tasks-src"))      # read-only mount of the repo's tasks/
RUNS_DIR = Path(os.environ.get("RUNS_DIR", "/runs"))
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")                     # ids become path components: nothing else is accepted
# harness-level connection loss: the agent did not fail, its runtime did (never scored)
LOST_RE = re.compile(r"gateway disconnected|connection (reset|refused|closed)|econnreset|socket hang up|broken pipe", re.I)
SEED_ATTEMPTS = 3
DEFAULT_TOKEN_BUDGET = 300_000
NUDGE = "\n\nBefore you start, check whether any of your skills or saved memory are relevant to this task."

_lock = threading.Lock()
_active: set = set()      # trial ids currently running (a retry must not run concurrently with its own timed-out predecessor)
_uids: set = set()        # uids currently in use (exclusive: two concurrent trials never share a user)
_next_uid = [20000]


def sync_tasks():
    """Copy tasks into a directory only root can read, so an agent (an unprivileged user) can never open the hidden
    tests or reference solutions. Re-run on worker restart to pick up task edits."""
    if TASKS_SRC.exists():
        shutil.rmtree(TASKS_DIR, ignore_errors=True)
        shutil.copytree(TASKS_SRC, TASKS_DIR)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(TASKS_DIR, 0o700)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUNS_DIR, 0o711)   # agents can enter their own dir but cannot list other trials


def task_hash(d: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(d)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def load_task(task_id: str) -> tuple[dict, Path]:
    d = TASKS_DIR / task_id
    return yaml.safe_load((d / "task.yaml").read_text()), d


def _listing(wd: Path):
    skip = {".git", ".pytest_cache", ".pytest_tmp", "__pycache__", ".opencode"}
    return sorted(str(p.relative_to(wd)) for p in wd.rglob("*")
                  if p.is_file() and not p.is_symlink() and not (set(p.relative_to(wd).parts) & skip))[:60]


def _alloc_uid() -> int:
    with _lock:
        for _ in range(40000):
            _next_uid[0] = 20000 + (_next_uid[0] - 20000 + 1) % 40000
            if _next_uid[0] not in _uids:
                _uids.add(_next_uid[0])
                return _next_uid[0]
    raise RuntimeError("no free sandbox uid")


def _infra(base, reason, events=(), usage=None, extra=None):
    return {**base, "status": "infra_error", "score": None, "reasoning": reason, "events": list(events),
            "usage": usage or {}, "cost_usd": 0, **(extra or {})}


async def run_trial(req: dict) -> dict:
    trial_id, task_id = str(req.get("trial_id", "")), str(req.get("task_id", ""))
    if not ID_RE.match(trial_id) or not ID_RE.match(task_id):
        raise ValueError("trial_id and task_id must match [A-Za-z0-9_-]{1,64}")
    base = {"trial_id": trial_id, "task_id": task_id}
    with _lock:
        if trial_id in _active:    # never touch the live run's directory or meter state
            return _infra(base, "trial already running on this worker (duplicate request)")
        _active.add(trial_id)
    uid = None
    try:
        uid = _alloc_uid()
        return await _run_trial(req, base, uid)
    finally:
        meter.release(trial_id)
        shutil.rmtree(RUNS_DIR / trial_id, ignore_errors=True)   # the trace is returned to the API; keep the disk small
        if uid is not None:
            harnesses.reap_all(trial_id, uid)
            with _lock:
                _uids.discard(uid)
        with _lock:
            _active.discard(trial_id)


async def _run_trial(req: dict, base: dict, uid: int) -> dict:
    trial_id, cfg = base["trial_id"], req["config"]
    task, tdir = load_task(base["task_id"])
    harness, s = HARNESSES[cfg["harness"]], cfg.get("settings", {})

    missing = set(task.get("requires", [])) - harness.capabilities
    if missing:  # harness cannot express this capability at all: not scored, not a failure
        return {**base, "status": "not_applicable", "score": None, "reasoning": f"{harness.name} lacks {sorted(missing)}",
                "events": [], "usage": {}, "cost_usd": 0}

    await asyncio.to_thread(harnesses.READY.wait)   # worker warm-up (Hermes template, OpenCode package cache)
    meter.release(trial_id)                          # a retried attempt must not inherit the failed attempt's state
    root = RUNS_DIR / trial_id
    work, home, seed_work = root / "work", root / "home", root / "seed_work"
    shutil.rmtree(root, ignore_errors=True)
    for d in (work, home, seed_work):
        d.mkdir(parents=True)
    os.chown(root, uid, uid)
    os.chmod(root, 0o700)
    if (tdir / "fixture").exists():
        shutil.copytree(tdir / "fixture", work, dirs_exist_ok=True, symlinks=True)

    limits = task.get("limits", {})
    max_turns = min(s.get("max_turns", 30), limits.get("max_turns", 30))
    budget = {"max_steps": max_turns, "max_tokens": s.get("token_budget", DEFAULT_TOKEN_BUDGET)}
    api_key = meter.register(trial_id)               # unguessable per-trial gateway secret (not the trial id)
    if s.get("temperature") is not None:
        meter.OVERRIDES[trial_id] = {"temperature": s["temperature"]}
    meter.BUDGETS[trial_id] = budget
    mk = lambda prompt, wd, skills: Ctx(trial_id, prompt, wd, home, cfg["model"], max_turns,  # noqa: E731
                                        limits.get("timeout_s", 300), skills, uid, api_key)
    skills = [str(tdir / "skills" / n) for n in task.get("setup", {}).get("skills", [])] if s.get("skills") else []
    started, events = time.time(), []

    # memory ON = a prior session told the agent a fact; its state dir is reused for the real task
    seed = task.get("setup", {}).get("memory_seed")
    if seed and s.get("memory"):
        # The agent decides whether to save the fact, and sometimes calls the memory tool without anything persisting.
        # Without a saved fact a "memory on" trial silently becomes a "no memory" trial, so retry the seed (max 3).
        # (If it still never saves, the trial is graded as it stands: not remembering is behaviour being measured.)
        for attempt in range(1, SEED_ATTEMPTS + 1):
            r0 = await asyncio.to_thread(harness.run, mk(seed, seed_work, []))
            events += [{**e, "phase": "seed", "attempt": attempt} for e in r0.events]
            if harness.memory_saved(home):
                break
        else:
            events.append({"type": "error", "message": f"memory_seed_unsaved: nothing persisted after {SEED_ATTEMPTS} attempts", "phase": "seed"})
        # the task phase gets the FULL step/token budget (memory ON must not start with a smaller one than memory OFF);
        # cost and token usage keep accumulating across both phases.
        meter.reset_budget(trial_id)

    prompt = task["prompt"] + (NUDGE if s.get("nudge") else "")
    res = await asyncio.to_thread(harness.run, mk(prompt, work, skills))
    events += [{**e, "phase": "task"} for e in res.events]
    duration_ms = int((time.time() - started) * 1000)
    usage = meter.usage_for(trial_id)
    exhausted = meter.EXHAUSTED.get(trial_id)
    resolved_model = meter.RESOLVED.get(trial_id)
    if exhausted:
        events.append({"type": "error", "message": f"budget_exhausted: {exhausted}", "phase": "task"})

    made_progress = any(e["type"] in ("assistant", "tool_call") for e in res.events)
    lost = next((e["message"] for e in res.events if e["type"] == "error" and LOST_RE.search(str(e.get("message", "")))), None)
    gateway_errors = usage.get("errors", 0)
    crashed = (not exhausted and not res.timed_out
               and (res.exit_code < 0 or (not res.complete and res.exit_code != 0)))
    infra = None
    if not res.timed_out and lost:
        infra = f"harness lost its connection: {lost[:160]}"
    elif not res.timed_out and not made_progress:
        # the harness produced nothing (OOM-kill, crash, gateway failure): not the agent's fault, never scored
        infra = f"harness produced no output (exit {res.exit_code}, gateway errors {gateway_errors}): {res.stderr.strip()[-200:]}"
    elif crashed:
        infra = f"harness terminated abnormally (exit {res.exit_code}, no completion marker): {res.stderr.strip()[-200:]}"
    elif not res.timed_out and usage.get("calls", 0) == 0:
        infra = "model gateway never called"

    if infra:
        status, score, reasoning = "infra_error", None, infra
    elif res.timed_out:
        status, score, reasoning = "timeout", 0.0, f"exceeded {limits.get('timeout_s', 300)}s"
    else:
        g = await graders.grade(task, tdir, work, res.final_text, uid)
        status = "grader_error" if g["error"] else "passed" if g["passed"] else "failed"
        score, reasoning = (None if g["error"] else g["score"]), g["reasoning"]
        events.append({"type": "grade", "score": score, "passed": g["passed"], "reasoning": reasoning})

    # Upstream trouble (429/5xx/hangs/dropped streams) may be what made the agent fail or run out of time: do not
    # blame the agent. A passing trial stays passed; the API retries infra_error trials and then excludes them.
    if status in ("failed", "timeout") and gateway_errors > 0 and not exhausted:
        status, score = "infra_error", None
        reasoning = f"{gateway_errors} model-gateway error(s) during the trial; outcome not attributable to the agent. Original: {reasoning[:200]}"

    return {**base, "status": status, "score": score, "reasoning": reasoning, "events": events,
            "final_text": res.final_text, "files": _listing(work), "usage": usage,
            "cost_usd": round(meter.cost_usd(cfg["model"], usage), 6), "duration_ms": duration_ms,
            "meta": {"harness_version": harnesses.VERSIONS.get(harness.name),
                     "model_deployment": os.environ.get(meter.MODELS[cfg["model"]]["deployment_env"]),
                     "model_resolved": resolved_model, "task_hash": task_hash(tdir), "budget": budget,
                     "nudge": bool(s.get("nudge")), "uid": uid}}
